#!/bin/sh
case "$1" in
bound|renew)
    ip addr flush dev "$interface"
    prefix=0
    saved_ifs=$IFS;IFS=.
    for octet in ${subnet:-255.255.255.0}; do
        while [ "$octet" -gt 0 ]; do prefix=$((prefix+octet%2));octet=$((octet/2));done
    done
    IFS=$saved_ifs
    ip addr add "$ip/$prefix" dev "$interface"
    ip link set "$interface" up
    ip route del default 2>/dev/null || true
    for gateway in $router; do ip route add default via "$gateway" dev "$interface";break;done
    : >/etc/resolv.conf
    for server in $dns; do echo "nameserver $server" >>/etc/resolv.conf;done
    cp /etc/resolv.conf /mini2/etc/resolv.conf
    ;;
esac
