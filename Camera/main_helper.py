from pymongo import MongoClient
import redis
import pickle
from constants import *

import logging

logging.getLogger("pymongo").setLevel(logging.WARNING)

def singleton(cls):
	instances = {}

	def get_instance(*args, **kwargs):
		if cls not in instances:
			instances[cls] = cls(*args, **kwargs)
		return instances[cls]

	return get_instance



@singleton
class MongoDBHelper:
	def __init__(self):
		# print("test")
		self.client = MongoClient(f'mongodb://{IP_ADDRESS}:{MONGO_PORT}')
		self.db = self.client[MONGODB]
		# return self.db
	
	def read_collection(self, collection):
		db = self.client[MONGODB]
		return db[collection]


@singleton
class RedisHelper:
    def __init__(self):
        
        self.client = redis.StrictRedis(host=IP_ADDRESS, port=REDIS_PORT, decode_responses=False)
        # print("Connected to Redis")

    def push_data(self, key, data):
       
        converted_data = pickle.dumps(data)
        
        self.client.set(key, converted_data)

    def pull_data(self, key):
       
        data = self.client.get(key)
        
        if data is None:
            # print(f"No data found for key: {key}")
            return None
        
        original_data = pickle.loads(data)
        # print(f"Data pulled for key: {key}")
        return original_data
	

   


	 