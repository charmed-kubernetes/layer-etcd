#!/bin/bash

set -e

mkdir -p $(pwd)/resources

while IFS="|" read app version file url checksum
do
  echo "Downloading $app Version: $version"
  curl -L -v $url -o resources/$file 2>> logfile.txt
  # make here a special case, if the file is not present
  calculated_sum=$(sha1sum "resources/$file" | /usr/bin/cut -f 1 -d " ")
  # compare checksum
  case "$calculated_sum" in
    "$checksum")
      echo -e " \033[m\033[42m  OK  \033[0m crypto signature compared and correct.";
	;;
	*)
	echo -e " \033[m\033[41m  ERROR  \033[0m cryptographic verification failed!";
  esac
done < "resources.dist"
