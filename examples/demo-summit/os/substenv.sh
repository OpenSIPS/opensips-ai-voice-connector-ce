#!/bin/bash
envsubst "$(printf '${%s} ' $(env | cut -d'=' -f1))"
