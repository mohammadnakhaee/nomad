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
import React, { useContext } from 'react'
import PropTypes from 'prop-types'
import { makeStyles } from '@material-ui/core/styles'
import { FilterSubMenu, filterMenuContext } from './FilterMenu'
import { InputGrid, InputGridItem } from '../input/InputGrid'
import InputPeriodicTable from '../input/InputPeriodicTable'
import InputField from '../input/InputField'
import InputSlider from '../input/InputSlider'
import { useUnits } from '../../../units'

const useStyles = makeStyles(theme => ({
  grid: {
    marginTop: theme.spacing(2)
  }
}))

const FilterSubMenuElements = React.memo(({
  value,
  ...rest
}) => {
  const {selected} = useContext(filterMenuContext)
  const visible = value === selected
  const styles = useStyles()
  const units = useUnits()

  return <FilterSubMenu value={value} {...rest}>
    <InputGrid className={styles.grid}>
      <InputGridItem xs={12}>
        <InputPeriodicTable
          quantity="results.material.elements"
          visible={visible}
        />
      </InputGridItem>
      <InputGridItem xs={6}>
        <InputField
          quantity="results.material.chemical_formula_hill"
          visible={visible}
          disableOptions
        />
      </InputGridItem>
      <InputGridItem xs={6}>
        <InputField
          quantity="results.material.chemical_formula_anonymous"
          visible={visible}
          disableOptions
        />
      </InputGridItem>
      <InputGridItem xs={12}>
        <InputSlider
          quantity="results.material.n_elements"
          visible={visible}
          step={1}
          units={units}
        />
      </InputGridItem>
    </InputGrid>
  </FilterSubMenu>
})
FilterSubMenuElements.propTypes = {
  value: PropTypes.string
}

export default FilterSubMenuElements