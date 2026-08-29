import { Input, Text, View } from '@tarojs/components'
import { useState } from 'react'

import './masked_date_input.scss'

const COMPACT_DATE_LENGTH = 8

export function MaskedDateInput({ label, onChange, value }: {
  readonly label: string
  readonly value: string
  readonly onChange: (value: string) => void
}) {
  const [focused, setFocused] = useState(false)
  const digits = normalizeCompactDateInput(value)
  const year = digits.slice(0, 4)
  const month = digits.slice(4, 6)
  const day = digits.slice(6, 8)
  const activeSegment = focused ? resolveActiveSegment(digits.length) : undefined

  return (
    <View className='masked-date-input'>
      <Text className='masked-date-input__label'>{label}</Text>
      <View className={`masked-date-input__field${focused ? ' masked-date-input__field--focused' : ''}`}>
        <View className='masked-date-input__display'>
          <DateSegment active={activeSegment === 'year'} placeholder='YYYY' value={year} />
          <Text className='masked-date-input__separator'>-</Text>
          <DateSegment active={activeSegment === 'month'} placeholder='MM' value={month} />
          <Text className='masked-date-input__separator'>-</Text>
          <DateSegment active={activeSegment === 'day'} placeholder='DD' value={day} />
        </View>
        <Input
          ariaLabel={`${label}，连续输入8位数字`}
          className='masked-date-input__native'
          cursor={digits.length}
          maxlength={COMPACT_DATE_LENGTH}
          type='number'
          value={digits}
          onBlur={() => setFocused(false)}
          onFocus={() => setFocused(true)}
          onInput={(event) => onChange(normalizeCompactDateInput(event.detail.value))}
        />
        {digits && (
          <Text
            className='masked-date-input__clear'
            onClick={(event) => {
              event.stopPropagation()
              onChange('')
            }}
          >×</Text>
        )}
      </View>
    </View>
  )
}

export function normalizeCompactDateInput(value: string): string {
  return value.replace(/\D/g, '').slice(0, COMPACT_DATE_LENGTH)
}

function DateSegment({ active, placeholder, value }: {
  readonly active: boolean
  readonly placeholder: string
  readonly value: string
}) {
  return (
    <Text className={`masked-date-input__segment${active ? ' masked-date-input__segment--active' : ''}${value ? '' : ' masked-date-input__segment--placeholder'}`}>
      {value || placeholder}
    </Text>
  )
}

function resolveActiveSegment(length: number): 'year' | 'month' | 'day' {
  if (length < 4) return 'year'
  if (length < 6) return 'month'
  return 'day'
}
