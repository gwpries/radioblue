#!/usr/bin/env python3

import requests
import numpy
import math
import time

ambient_db = -2.4

stream_url = 'http://192.168.1.120:8000/stream' 
r = requests.get(stream_url, stream=True)

last_audio_time = time.time()

def get_stream():
    return requests.get(stream_url, stream=True)

while True:
    with open('stream.mp3', 'wb') as f:
        r = get_stream()
        for block in r.iter_content(4096):
            samps = 0
            try:
                samps = numpy.frombuffer(block, dtype = numpy.int16)
            except ValueError:
                print("stream offline")
                time.sleep(1)
                r = get_stream()
                continue
            rms = numpy.sqrt(numpy.mean(samps**2))
            db = 20*numpy.log10(rms)
            if not math.isnan(db) and db < 30:
                last_audio_time = time.time()
        
            diff_time = time.time() - last_audio_time 
            print(f"{int(diff_time)} seconds since last audio packet (last read: {db} db)")
