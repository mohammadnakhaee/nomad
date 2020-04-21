# Copyright 2018 Markus Scheidgen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an"AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This dockerfile describes an image that can be used to run the
# - nomad processing worker
# - nomad app (incl serving the gui)

# The dockerfile is multistaged to use a fat, more convinient build image and
# copy only necessities to a slim final image

# We use slim for the final image
FROM python:3.6-slim as final

# First, build all python stuff in a python build image
FROM python:3.6-stretch as build
RUN mkdir /install

# Install some specific dependencies necessary for the build process
RUN pip install --upgrade pip
RUN pip install fastentrypoints
RUN pip install pyyaml
RUN pip install numpy

# Install some specific dependencies to make use of docker layer caching
RUN pip install cython>=0.19
RUN pip install pandas
RUN pip install h5py
RUN pip install hjson
RUN pip install scipy
RUN pip install scikit-learn==0.20.2
RUN pip install ase==3.19.0
RUN pip install Pint
RUN pip install matid
RUN pip install mdtraj==1.9.1
RUN pip install mdanalysis==0.16.2

# Make will be necessary to build the docs with sphynx
RUN apt-get update && apt-get install -y make
RUN apt-get update && apt-get install -y vim

# Copy files and install nomad@FAIRDI
WORKDIR /install
COPY . /install
RUN python setup.py compile
RUN pip install .[all]
RUN python setup.py sdist
WORKDIR /install/docs
RUN make html
RUN \
    find /usr/local/lib/python3.6/ -name 'tests' ! -path '*/networkx/*' -exec rm -r '{}' + && \
    find /usr/local/lib/python3.6/ -name 'test' -exec rm -r '{}' + && \
    find /usr/local/lib/python3.6/site-packages/ -name '*.so' -print -exec sh -c 'file "{}" | grep -q "not stripped" && strip -s "{}"' \;

# Second built the GUI in a gui build image
FROM node:latest as gui_build
RUN mkdir -p /app
WORKDIR /app
ENV PATH /app/node_modules/.bin:$PATH
COPY gui/package.json /app/package.json
COPY gui/yarn.lock /app/yarn.lock
RUN yarn
COPY gui /app
RUN yarn run build

# Third, create a slim final image
FROM final

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && apt-get install -y libmagic-dev curl

# copy the sources for tests, coverage, qa, etc.
COPY . /app
WORKDIR /app
# transfer installed packages from dependency stage
COPY --from=build /usr/local/lib/python3.6/site-packages /usr/local/lib/python3.6/site-packages
RUN echo "copy 1"
# copy the meta-info, since it files are loaded via relative paths. TODO that should change.
COPY --from=build /install/dependencies/nomad-meta-info /app/dependencies/nomad-meta-info
RUN echo "copy 2"
# copy the documentation, its files will be served by the API
COPY --from=build /install/docs/.build /app/docs/.build
RUN echo "copy 3"
# copy the source distribution, its files will be served by the API
COPY --from=build /install/dist /app/dist
RUN echo "copy 4"
# copy the nomad command
COPY --from=build /usr/local/bin/nomad /usr/bin/nomad
RUN echo "copy 5"
# copy the gui
RUN mkdir -p /app/gui
COPY --from=gui_build /app/build /app/gui/build
RUN echo "copy 6"

RUN mkdir -p /app/.volumes/fs
RUN useradd -ms /bin/bash nomad
RUN chown -R nomad /app
RUN chmod a+rx run.sh
USER nomad

VOLUME /app/.volumes/fs

EXPOSE 8000
