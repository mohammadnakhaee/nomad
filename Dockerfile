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
FROM python:3.7-slim as final

# Build all python stuff in a python build image
FROM python:3.7-stretch as build
RUN mkdir /install

# Install linux package dependencies
RUN apt-get update
RUN apt-get install -y --no-install-recommends libgomp1
RUN apt-get install -y libmagic-dev curl vim make cmake swig libnetcdf-dev

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
RUN pip install mdtraj
RUN pip install mdanalysis

# Make will be necessary to build the docs with sphynx
RUN apt-get update && apt-get install -y make
RUN apt-get update && apt-get install -y vim

# Install pymolfile (required by some parsers)
RUN git clone -b nomad-fair https://gitlab.mpcdf.mpg.de/nomad-lab/pymolfile.git
WORKDIR /pymolfile/
RUN python3 setup.py install
RUN rm -rf /pymolfile

# Copy files and install nomad@FAIRDI
WORKDIR /install
COPY . /install
RUN python setup.py compile
RUN pip install .[all]
RUN python setup.py sdist
RUN cp dist/nomad-lab-*.tar.gz dist/nomad-lab.tar.gz
RUN python -m nomad.cli dev metainfo > gui/src/metainfo.json
RUN python -m nomad.cli dev search-quantities > gui/src/searchQuantities.json
RUN python -m nomad.cli dev toolkit-metadata > gui/src/toolkitMetadata.json
WORKDIR /install/docs
RUN make html
RUN \
    find /usr/local/lib/python3.7/ -name 'tests' ! -path '*/networkx/*' -exec rm -r '{}' + && \
    find /usr/local/lib/python3.7/ -name 'test' -exec rm -r '{}' + && \
    find /usr/local/lib/python3.7/site-packages/ -name '*.so' -print -exec sh -c 'file "{}" | grep -q "not stripped" && strip -s "{}"' \;

# Built the GUI in the gui build image
FROM node:14.8 as gui_build
RUN mkdir -p /app
WORKDIR /app
ENV PATH /app/node_modules/.bin:$PATH
COPY gui/package.json /app/package.json
COPY gui/yarn.lock /app/yarn.lock
RUN yarn
COPY gui /app
COPY --from=build /install/gui/src/metainfo.json /app/src/metainfo.json
COPY --from=build /install/gui/src/searchQuantities.json /app/src/searchQuantities.json
COPY --from=build /install/gui/src/parserMetadata.json /app/src/parserMetadata.json
COPY --from=build /install/gui/src/toolkitMetadata.json /app/src/toolkitMetadata.json
RUN yarn run build

# Build the Encyclopedia GUI in the gui build image
RUN mkdir -p /encyclopedia
WORKDIR /encyclopedia
COPY dependencies/encyclopedia-gui/client/src /encyclopedia/src
COPY dependencies/encyclopedia-gui/client/webpack.config.js /encyclopedia/webpack.config.js
RUN npm install webpack webpack-cli
RUN npx webpack --mode=production

# Third, create a slim final image
FROM final

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && apt-get install -y libmagic-dev curl

# copy the sources for tests, coverage, qa, etc.
COPY . /app
WORKDIR /app
# transfer installed packages from dependency stage
COPY --from=build /usr/local/lib/python3.7/site-packages /usr/local/lib/python3.7/site-packages
RUN echo "copy 1"
# copy the documentation, its files will be served by the API
COPY --from=build /install/docs/.build /app/docs/.build
RUN echo "copy 2"
# copy the source distribution, its files will be served by the API
COPY --from=build /install/dist /app/dist
RUN echo "copy 3"
# copy the nomad command
COPY --from=build /usr/local/bin/nomad /usr/bin/nomad
RUN echo "copy 4"
# copy the gui
RUN mkdir -p /app/gui
COPY --from=gui_build /app/build /app/gui/build
RUN echo "copy 5"
# copy the encyclopedia gui production code
COPY --from=gui_build /encyclopedia /app/dependencies/encyclopedia-gui/client
RUN rm -rf /app/dependencies/encyclopedia-gui/client/src
RUN echo "copy 6"

RUN mkdir -p /app/.volumes/fs
RUN useradd -ms /bin/bash nomad
RUN chown -R nomad /app
RUN chmod a+rx run.sh
USER nomad

VOLUME /app/.volumes/fs

EXPOSE 8000
