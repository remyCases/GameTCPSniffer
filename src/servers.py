# Copyright (C) 2025 Rémy Cases
# See LICENSE file for extended copyright information.
# This file is part of GameTCPSniffer project from https://github.com/remyCases/GameTCPSniffer.

import asyncio
import queue
import re
import subprocess
from typing import Callable, List, Tuple

from scapy.all import Packet
from scapy.layers.inet import IP, TCP

from src.utils import CommunicationFlag, Message, is_client


def get_game_servers(ports: List[int]) -> List[Tuple[str, int]]:
    """Find current server IPs given some specific ports by scanning netstat"""
    try:
        # Get netstat output
        result = subprocess.run(['netstat', '-an'], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if result.returncode != 0:
            print(f"Netstat failed: {result.stderr!r}")
            return []

        try:
            # decode stdout as utf8 string
            output = result.stdout.decode('utf-8')
        except UnicodeDecodeError:
            # fallback to cp1252 with error handling
            output = result.stdout.decode('cp1252', errors='ignore')

        lines = output.split('\n')
        servers: List[Tuple[str, int]] = []

        for line in lines:
            if "ESTABLISHED" in line and "TCP" in line:
                # Extract IP and port from netstat line
                match = re.search(r"(\d+\.\d+\.\d+\.\d+):(\d+)[\s]+(\d+\.\d+\.\d+\.\d+):(\d+)", line)
                if match:
                    ip = match.group(3)
                    port = int(match.group(4))

                    # Look for our target ports
                    if port in ports:
                        # Make sure it's not localhost
                        if not is_client(ip):
                            servers.append((ip, port))
        
        return servers
    
    except Exception as e:
        print(f"Error scanning netstat: {e}")
        return []

def generate_packet_handler(
    db_queue_for_statemachine: queue.Queue[Message], 
    db_queue_for_decoder: queue.Queue[Message]
) -> Callable[[Packet, List[str], int], None]:

    def packet_handler(pkt: Packet, servers: List[str], filter_payload_len: int) -> None:
        """
        Filters TCP packets following a list of servers.
        
        Args:
            pkt: Scapy packet object
            servers: List of server IPs to monitor
            filter_payload_len: Expected ACK packet size (-1 for no filtering)
        """

        if pkt.haslayer(TCP) and pkt.haslayer(IP):
            src_ip = pkt[IP].src
            dst_ip = pkt[IP].dst
            
            if (src_ip in servers or dst_ip in servers):
                payload = bytes(pkt[TCP].payload)

                if filter_payload_len == -1: # no filtering, display everything
                    msg = Message(src_ip, dst_ip, pkt, CommunicationFlag.OTHER)
                    try:
                        db_queue_for_decoder.put_nowait(msg)
                    except asyncio.QueueFull:
                        print("Database queue full !")
                    return

                if filter_payload_len > 0 and len(payload) == filter_payload_len and not is_client(src_ip):
                    msg = Message(src_ip, dst_ip, pkt, CommunicationFlag.ACK)

                else:
                    msg = Message(src_ip, dst_ip, pkt, CommunicationFlag.OTHER)
 
                # Non-blocking queue put
                try:
                    db_queue_for_statemachine.put_nowait(msg)
                except asyncio.QueueFull:
                    print("Database queue full !")

    return packet_handler
