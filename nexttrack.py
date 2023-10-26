#!/usr/bin/env python3
"""Radio Blue Next Track"""

import radiobluequeue

def main():
    """Main routine"""
    rbq = radiobluequeue.RadioBlueQueue()
    rbq.load_config()
    rbq.test_server_connection()
    rbq.get_client()
    rbq.next_track()
    
if __name__ == '__main__':
    main()

