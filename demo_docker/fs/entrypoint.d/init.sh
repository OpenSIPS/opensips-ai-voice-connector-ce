#!/bin/bash

sed -E -i "s/internal_sip_port=[^\"]+/internal_sip_port=${FS_SIP_PORT}/" /etc/freeswitch/vars.xml
sed -i "s/stun:stun.freeswitch.org/${HOST_IP}/" /etc/freeswitch/vars.xml
sed -E -i "s/global_codec_prefs=[^\*]+/global_codec_prefs=PCMU,PCMA/" /etc/freeswitch/vars.xml
sed -E -i "s/outbound_codec_prefs=[^\*]+/outbound_codec_prefs=PCMU,PCMA/" /etc/freeswitch/vars.xml

cp /tmp/dialplan/public.xml /etc/freeswitch/dialplan/public.xml
