import { Image, Text, View } from '@tarojs/components'
import { useState } from 'react'

import { resolveAssetUrl } from '@/utils/asset_url'

export interface BeadColorSwatchProps {
  readonly className: string
  readonly emptyClassName?: string
  readonly emptyLabel?: string
  readonly swatchHex: string | null
  readonly swatchImageUrl: string | null
}

export function BeadColorSwatch({
  className,
  emptyClassName,
  emptyLabel,
  swatchHex,
  swatchImageUrl,
}: BeadColorSwatchProps) {
  const [imageFailed, setImageFailed] = useState(false)

  if (swatchHex) {
    return (
      <View
        className={`${className} bead-color-swatch--hex`}
        style={{ backgroundColor: swatchHex }}
      />
    )
  }

  if (swatchImageUrl && !imageFailed) {
    return (
      <Image
        className={`${className} bead-color-swatch--image`}
        lazyLoad
        mode='aspectFill'
        src={resolveAssetUrl(swatchImageUrl)}
        onError={() => setImageFailed(true)}
      />
    )
  }

  const emptyClasses = [className, emptyClassName, 'bead-color-swatch--empty']
    .filter(Boolean)
    .join(' ')
  return (
    <View className={emptyClasses}>
      {emptyLabel && <Text>{emptyLabel}</Text>}
    </View>
  )
}
