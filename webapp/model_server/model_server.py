import os
import json
from time import sleep
from shutil import copyfile
import logging

logging.basicConfig(level=logging.INFO)

import boto3

from config import *
from model import load_model


SQS_QUEUE = boto3.resource("sqs").Queue(SQS_URL)
INPUT_S3_BUCKET = boto3.resource("s3").Bucket(INPUT_S3_BUCKET_NAME)
OUTPUT_S3_BUCKET = boto3.resource("s3").Bucket(OUTPUT_S3_BUCKET_NAME)

# Load the model once, during deployment
MODEL = load_model(MODEL_PATH)

# How long should we wait if the queue is empty
# TODO: Change to exponential backoff
SLEEP_TIME_IN_SEC = 10

# Create the output dir if it doesn't exist
if not os.path.exists(OUTPUT_DIR):
    os.mkdir(OUTPUT_DIR)

def s3_image_key_gen():
    while True:
        messages = SQS_QUEUE.receive_messages(MaxNumberOfMessages=10)
        if not messages:
            logging.info("Sleeping for %d seconds", SLEEP_TIME_IN_SEC)
            sleep(SLEEP_TIME_IN_SEC)
            continue

        logging.info("Received %d messages", len(messages))

        for message in messages:
            m_dict = json.loads(message.body)
            print(m_dict)
            obj_key = m_dict["Records"][0]["s3"]["object"]["key"]
            obj_key = obj_key.replace("+", " ")
            yield obj_key, message.receipt_handle


def cleanup(s3_image_key):
    os.remove(s3_image_key)
    os.remove(OUTPUT_DIR + "/" + s3_image_key)


def create_mask(s3_image_key):
    # Use the model to create the mask files and the visualization
    # Dummy, simply copy the file as is
    copyfile(s3_image_key, OUTPUT_DIR + "/" + s3_image_key)
    return OUTPUT_DIR + "/" + s3_image_key


def main():
    logging.info("Starting up...")
    # Indefinite loop to listen to messages on the queue
    for s3_image_key, receipt_handle in s3_image_key_gen():
        logging.info("Processing image %s with handle %s", s3_image_key, receipt_handle)

        # Pick up the image from S3
        INPUT_S3_BUCKET.download_file(s3_image_key, s3_image_key)

        # Get the mask predictions and annotations
        output_file = create_mask(s3_image_key)

        # Upload to output S3 bucket
        OUTPUT_S3_BUCKET.upload_file(output_file, s3_image_key)

        # Cleanup files
        cleanup(s3_image_key)

        # Delete from queue, so that we don't reprocess it
        SQS_QUEUE.delete_messages(Entries=[{'Id': 'dummy', 'ReceiptHandle': receipt_handle}])

        logging.info("Successfully processed image %s with handle %s", s3_image_key, receipt_handle)


if __name__ == "__main__":
    main()
