#                       Dockerization of Congress:
#
#  This Docker image will create a minimal environment to run the Congress
#  scrapers in. This provides isolation from the host, and allows testing
#  in an environment that's as close to production as you can.
#
#
#  You can build this image by running:
#
#    docker build --rm -t unitedstates/congress .
#
#
#  Running the scraper should be as easy as:
#
#    export CONGRESS_OUTPUT_DIR=/tmp/congres
#
#    docker run \
#      -t --rm \
#      -v ${CONGRESS_OUTPUT_DIR}:/congress \
#      unitedstates/congress \
#      ...
#
#
#   Where [...] is something like `bills`, or any other arguments to the
#   `run` script.
#
#   The data produced by the scrape will end up at ${CONGRESS_OUTPUT_DIR}
#   on the host. This path may be any path on the host.
#
#  One good pattern is to write this out to the /srv/ tree, for example,
#  /srv/pault.ag/congress/ or /srv/io.unitedstates/congress/

FROM        debian:jessie
MAINTAINER  Paul R. Tagliamonte <paultag@sunlightfoundation.com>

RUN apt-get update && apt-get install -y \
    git python-dev libxml2-dev libxslt1-dev libz-dev python-pip wget

RUN mkdir -p /opt/theunitedstates.io/
ADD . /opt/theunitedstates.io/congress/
WORKDIR /opt/theunitedstates.io/congress/

RUN pip install -r requirements.txt

RUN echo "/opt/theunitedstates.io/congress/" > /usr/lib/python2.7/dist-packages/congress.pth

RUN mkdir -p /congress
WORKDIR /congress

CMD []
ENTRYPOINT ["/opt/theunitedstates.io/congress/run"]
