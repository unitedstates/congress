import os
import json
import argparse
import boto3
from datetime import datetime

def upload_file(data_array, access_key_id, secret_access_key):
    client = boto3.client('s3', aws_access_key_id=access_key_id, aws_secret_access_key=secret_access_key)
    key_name = "development/roll-call-vote-import"
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    client.put_object(
        Body=json.dumps(data_array),
        Bucket='roll-call-votes',
        Key= f"{key_name}-{timestamp}"
    )

    print("done")

def main():
    parser = argparse.ArgumentParser(description="Upload JSON data to an S3 bucket")
    parser.add_argument("--access-key", required=True, help="AWS access key ID")
    parser.add_argument("--secret-key", required=True, help="AWS secret access key")
    args = parser.parse_args()

    script_directory = os.path.dirname(os.path.abspath(__file__))
    data_array = []

    for root, dirs, files in os.walk(script_directory):
        for file_name in files:
            # Check if the file ends with '.json'
            if file_name.endswith(".json"):
                # Create the full path to the JSON file
                json_file_path = os.path.join(root, file_name)

                # Now you can work with the JSON file
                with open(json_file_path, "r") as json_file:
                    data = json.load(json_file)
                    data_array.append(data)

    upload_file(data_array, args.access_key, args.secret_key)

if __name__ == "__main__":
    main()
