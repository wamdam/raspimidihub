#!/bin/bash
sudo iptables -t nat -A POSTROUTING -o wlp0s20f3 -j MASQUERADE
sudo iptables -A FORWARD -i enx4865ee1b564c -o wlp0s20f3 -j ACCEPT
sudo iptables -A FORWARD -i wlp0s20f3 -o enx4865ee1b564c -m state --state RELATED,ESTABLISHED -j ACCEPT
