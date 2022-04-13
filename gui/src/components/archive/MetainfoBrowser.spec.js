/*
 * Copyright The NOMAD Authors.
 *
 * This file is part of NOMAD. See https://nomad-lab.eu for further info.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
import React from 'react'
import { join, basename } from 'path'
import { waitFor } from '@testing-library/dom'
import { render, screen } from '../conftest.spec'
import { getLane, browseRecursively } from './conftest.spec'
import MetainfoBrowser from './MetainfoBrowser'

function metainfoItemFilter(parentPath, items, encounteredLastTwoSegments) {
  // The metainfo tree is very big, so we need to limit the crawling. This method is used
  // to make the selection.
  if (parentPath.split('/').length === 1) {
    // Root - filter nothing
    return Object.keys(items)
  }
  const rv = []
  const encounteredPrefixes = {}
  let countKeysWithoutPrefixes = 0
  for (const itemKey of Object.keys(items)) {
    const lastTwoSegments = join(basename(parentPath), itemKey)
    if (!encounteredLastTwoSegments[lastTwoSegments]) {
      encounteredLastTwoSegments[lastTwoSegments] = true
      let include = false

      const parts = itemKey.split(/[.@]/)
      const prefixes = parts.slice(0, parts.length - 1)
      if (prefixes.length === 0) {
        countKeysWithoutPrefixes++
        include = countKeysWithoutPrefixes < 3
      } else {
        // We have some number of prefixes. Include only if at least one of the prefixes is new.
        for (const prefix of prefixes) {
          if (!encounteredPrefixes[prefix]) {
            include = true
            encounteredPrefixes[prefix] = true
          }
        }
      }
      if (include) {
        rv.push(itemKey)
      }
    }
  }
  return rv
}

test('Browse reursively', async () => {
  const consoleLogSpy = jest.spyOn(console, 'log')
  const consoleErrorSpy = jest.spyOn(console, 'error')
  try {
    render(<MetainfoBrowser />)
    await waitFor(() => {
      expect(screen.getByText(/archive root section/i)).toBeVisible()
    })

    const encounteredLastTwoSegments = {}

    await browseRecursively(getLane(0), 0, '*MetaInfoBrowser*', consoleLogSpy, consoleErrorSpy, metainfoItemFilter, encounteredLastTwoSegments)
  } finally {
    consoleLogSpy.mockRestore()
    consoleErrorSpy.mockRestore()
  }
}, 360000)
