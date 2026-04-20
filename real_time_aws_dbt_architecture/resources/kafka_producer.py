"""
NYC Green Taxi Kafka Producer
=============================
Generates simulated NYC Green Taxi ride data and publishes it to an MSK Serverless
Kafka topic. Each record represents a single taxi trip with pickup/dropoff locations,
fare details, timestamps, and trip metadata.

The script:
1. Authenticates to MSK Serverless using IAM (via OAUTHBEARER/SASL_SSL)
2. Generates 100 randomized taxi ride records
3. Sends each record as a JSON message to the configured Kafka topic
4. Prints send confirmation for each record

Usage (on the EC2 instance):
    python3 producer.py

Prerequisites:
    - pip install kafka-python aws-msk-iam-sasl-signer-python
    - EC2 instance must have the Kafka_Cluster_Access IAM role attached
    - The target topic must already exist (create with kafka-topics.sh)

Note: This uses dummy/randomized data. For a real-data alternative, the NYC
Taxi & Limousine Commission provides a free API (no auth required):
    https://data.cityofnewyork.us/resource/gkne-dk5s.json?$limit=100
"""

# --- Imports ---
# KafkaProducer: the main class for sending messages to Kafka topics
from kafka import KafkaProducer

# AbstractTokenProvider: base class we extend to provide IAM auth tokens
from kafka.sasl.oauth import AbstractTokenProvider

# MSKAuthTokenProvider: AWS library that generates short-lived IAM tokens
# for authenticating to MSK Serverless (replaces username/password)
from aws_msk_iam_sasl_signer import MSKAuthTokenProvider

# json: serializes Python dicts to JSON strings for Kafka messages
import json

# random: generates random ride data (locations, fares, passenger counts)
import random

# datetime/timedelta: generates realistic timestamps for pickup/dropoff
from datetime import datetime, timedelta

# --- Configuration ---
# UPDATE THESE for your environment:
topicname = 'realtimeridedata'
BROKERS = 'boot-azgxfx6o.c1.kafka-serverless.us-east-1.amazonaws.com:9098'  # Replace with your bootstrap server
region = 'us-east-1'  # Replace with your region (e.g. 'eu-north-1')


# --- IAM Authentication ---
# MSK Serverless requires IAM-based auth (no username/password option).
# This class generates short-lived OAuth tokens using the EC2 instance's
# IAM role. The KafkaProducer calls token() automatically before each
# connection and when the token expires.
class MSKTokenProvider(AbstractTokenProvider):
    def __init__(self):
        super().__init__()

    def token(self):
        # Generates a fresh IAM auth token for the configured region
        token, _ = MSKAuthTokenProvider.generate_auth_token(region)
        return token

    def extend_token(self):
        return self.token()

    def principal(self):
        return "msk-iam-user"


tp = MSKTokenProvider()

# --- Kafka Producer Setup ---
# Creates a producer that:
# - Connects to MSK via the bootstrap server endpoint
# - Serializes each message value as JSON (dict → JSON string → bytes)
# - Uses SASL_SSL + OAUTHBEARER for IAM authentication
# - Retries on transient failures (500ms backoff, 20s timeout)
producer = KafkaProducer(
    bootstrap_servers=BROKERS,
    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
    retry_backoff_ms=500,
    request_timeout_ms=20000,
    security_protocol='SASL_SSL',
    sasl_mechanism='OAUTHBEARER',
    sasl_oauth_token_provider=tp,
)

# --- Reference Data ---
# NYC boroughs and their neighborhoods for pickup/dropoff locations
city = ['Manhattan', 'Brooklyn', 'Queens', 'Bronx', 'Staten Island']
manhattan_locations = ['Upper East Side', 'Upper West Side', 'Midtown', 'Downtown', 'Chelsea', 'Harlem']
brooklyn_locations = ['Williamsburg', 'Park Slope', 'DUMBO', 'Brooklyn Heights', 'Bushwick']
queens_locations = ['Astoria', 'Long Island City', 'Flushing', 'Jackson Heights']
bronx_locations = ['Yankee Stadium', 'Fordham', 'Pelham Bay']
staten_island_locations = ['St. George', 'Tottenville', 'New Dorp']

payment_types = ['Credit card', 'Cash', 'No charge', 'Dispute', 'Unknown']
rate_codes = ['Standard', 'JFK', 'Newark', 'Nassau/Westchester', 'Negotiated', 'Group ride']
trip_types = ['Street-hail', 'Dispatch']


def get_pickup_loc(city):
    """Returns a random neighborhood within the given borough."""
    if city == 'Manhattan':
        return random.choice(manhattan_locations)
    elif city == 'Brooklyn':
        return random.choice(brooklyn_locations)
    elif city == 'Queens':
        return random.choice(queens_locations)
    elif city == 'Bronx':
        return random.choice(bronx_locations)
    else:
        return random.choice(staten_island_locations)


def get_dropoff_loc(pickup_city):
    """Returns a random dropoff neighborhood — 70% chance same borough, 30% different."""
    if random.random() < 0.7:
        return get_pickup_loc(pickup_city)
    else:
        return get_pickup_loc(random.choice([b for b in city if b != pickup_city]))


def generate_green_taxi_data(trip_id):
    """
    Generates a single simulated NYC Green Taxi trip record.
    Returns a dict with all trip fields (timestamps, locations, fares, etc.)
    """
    # Random date in the last 30 days as base for pickup time
    base_time = datetime.now() - timedelta(days=random.randint(1, 30))

    # Pickup location
    pickup_city = random.choice(city)
    pickup_loc = get_pickup_loc(pickup_city)

    # Dropoff location — 70% same borough, 30% different
    dropoff_city = pickup_city if random.random() < 0.7 else random.choice([b for b in city if b != pickup_city])
    dropoff_loc = get_dropoff_loc(dropoff_city)

    # Trip metrics
    trip_dst = round(random.uniform(0.5, 25.0), 2)
    fare_amt = round(trip_dst * 2.5 + random.uniform(2.0, 10.0), 2)
    fare_amt = round(fare_amt * random.uniform(0.1, 0.25), 2) if random.random() < 0.8 else 0.0
    tolls_amt = round(random.uniform(0.0, 10.0), 2) if random.random() < 0.3 else 0.0
    total_amt = fare_amt + fare_amt + tolls_amt

    # Timestamps
    pickup_time = base_time
    dropoff_time = pickup_time + timedelta(minutes=random.randint(5, 90))

    taxi_data = {
        "trip_id": f"trip_{trip_id:04d}",
        "vendor_id": random.randint(1, 2),
        "pickup_dt": pickup_time.strftime("%Y-%m-%d %H:%M:%S"),
        "dropoff_dt": dropoff_time.strftime("%Y-%m-%d %H:%M:%S"),
        "passenger_cnt": random.randint(1, 6),
        "trip_dst": trip_dst,
        "pickup_city": pickup_city,
        "pickup_loc": pickup_loc,
        "dropoff_city": dropoff_city,
        "dropoff_loc": dropoff_loc,
        "fare_amt": fare_amt,
        "tolls_amt": tolls_amt,
        "total_amt": total_amt,
        "payment_typ": random.choice(payment_types),
        "rate_cd": random.choice(rate_codes),
        "trip_typ": random.choice(trip_types),
        "congestion_surcharge": round(random.uniform(0.0, 2.5), 2) if random.random() < 0.4 else 0.0,
        "airport_fee": round(random.uniform(0.0, 1.25), 2) if random.random() < 0.2 else 0.0,
        "event_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    return taxi_data


# --- Main: Send Records ---
total_records = 100
sent_count = 0

print(f"Starting to send {total_records} NYC Green Taxi records...")

for i in range(total_records):
    data = generate_green_taxi_data(i + 1)

    try:
        # Send the record to Kafka. producer.send() is async — it returns a Future.
        future = producer.send(topicname, value=data)

        # Flush forces all buffered messages to be sent immediately.
        # Without this, messages are batched and may not send until the buffer is full.
        producer.flush()

        # .get(timeout=10) blocks until the broker acknowledges receipt.
        # If the broker doesn't respond in 10 seconds, it raises an exception.
        record_metadata = future.get(timeout=10)

        sent_count += 1
        print(f"✅ Sent record {sent_count}/{total_records}: Trip ID {data['trip_id']} - ${data['total_amt']} - {data['pickup_city']} to {data['dropoff_city']}")

    except Exception as e:
        print(f"❌ Error sending message: {e}")
        break

print(f"\nFinished! Successfully sent {sent_count} out of {total_records} records.")
producer.close()
