import logging
from flask import Flask, request, jsonify, send_from_directory
import os
import uuid
import json
from google.cloud import pubsub_v1, datastore, storage
import time
from kubernetes import client, config

app = Flask(__name__)
os.environ["GCLOUD_PROJECT"] = "thinking-banner-421414"
bucket_name = 'thinking-banner-421414_cloudbuild'
task_id = str(uuid.uuid4())

project_id = "thinking-banner-421414"
decompose_topic_id = "decompose-video"
decompose_subscription_paths = []
process_subscription_id = "process-video-sub"

publisher = pubsub_v1.PublisherClient()
subscriber = pubsub_v1.SubscriberClient()
decompose_topic_path = publisher.topic_path(project_id, decompose_topic_id)
process_subscription_path = subscriber.subscription_path(project_id, process_subscription_id)


def callback(message):
    print(f"Dropping message: {message.data}")
    message.ack()


def clear_subscription(subscription_path):
    future = subscriber.subscribe(subscription_path, callback)
    try:
        future.result(timeout=10)
    except Exception as e:
        future.cancel()
        print(f"Subscription cleared: {subscription_path}")


def checkSubPub():
    '''create the Pub/Sub if not exist'''
    try:
        publisher.get_topic(topic=decompose_topic_path)
    except:
        publisher.create_topic(name=decompose_topic_path)


def getPodCount():
    config.load_kube_config()
    v1 = client.CoreV1Api()
    pods = v1.list_namespaced_pod(namespace='default')
    return len(pods.items)


def create_table():
    '''create NoSQL table to store task status'''
    client = datastore.Client(project='thinking-banner-421414')
    task_key = client.key("Status", task_id)
    task = datastore.Entity(key=task_key)

    task["status"] = "Preprocessing"
    task["update_time"] = time.ctime()

    client.put(task)


def getProgress(task_id):
    client = datastore.Client(project='thinking-banner-421414')
    key = client.key('Status', task_id)
    task = client.get(key)
    return task['status']


def upload_blob(source_file_name, destination_blob_name):
    '''upload file to bucket'''
    storage_client = storage.Client(project='thinking-banner-421414')
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file_name)
    download_url = "https://storage.googleapis.com/" + bucket_name + "/" + destination_blob_name
    return download_url


@app.route('/')
def index():
    return send_from_directory('static', 'web.html')


@app.route('/upload1', methods=['POST'])
def videoProcess():
    video = request.files['videoFile']
    image = request.files['watermarkFile']

    video_name = video.filename
    video_path = "/tmp/" + video_name
    image_path = "/tmp/" + image.filename

    video.save(video_path)
    image.save(image_path)

    create_table()
    video_url = upload_blob(video_path, video_name)
    image_url = upload_blob(image_path, image.filename)
    message = {
        'task_id': task_id,
        'video_url': video_url,
        'image_url': image_url,
        'pod_num': pod_num
    }
    publisher.publish(decompose_topic_path, json.dumps(message).encode('utf-8'))
    logging.warning(message)
    return jsonify({"message": "Task_id: " + task_id})


@app.route('/upload2', methods=['POST'])
def urlProcess():
    video_url = request.form['videoURL']
    image_url = request.form['watermarkURL']

    required_string = ['cloud', 'storage', 'google', '.com', 'https://']

    if not (all(substr in video_url for substr in required_string) and
            all(substr in image_url for substr in required_string)):
        return jsonify({"message": "Wrong URL input. Please check your URL form."}), 500

    create_table()
    message = {
        'task_id': task_id,
        'video_url': video_url,
        'image_url': image_url,
        'pod_num': pod_num
    }
    publisher.publish(decompose_topic_path, json.dumps(message).encode('utf-8'))
    logging.warning(message)
    return jsonify({"message": "task_id is " + task_id})


@app.route('/tokenProcess', methods=['GET'])
def tokenProcess():
    try:
        input_task_id = request.args.get('taskID')
        progress = getProgress(input_task_id)
        return jsonify({"message": progress})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    pod_num = getPodCount()
    for i in range(pod_num):
        decompose_subscription_path = subscriber.subscription_path(project_id, "decompose-video-sub-" + str(i))
        clear_subscription(decompose_subscription_path)
    clear_subscription(process_subscription_path)
    checkSubPub()
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))