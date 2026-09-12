import { join } from 'node:path'

import { compile } from 'sass'

const css = compile(join(__dirname, '..', 'index.scss')).css

describe('微信自定义 TabBar 布局', () => {
  it('在 dock 内预留透明上沿，并用独立 surface 绘制瓷白托盘', () => {
    const dockRule = getRule('.root-tab-bar__dock')
    const surfaceRule = getRule('.root-tab-bar__surface')

    expect(dockRule).toContain('position: relative')
    expect(dockRule).toContain('height: 158px')
    expect(dockRule).toContain('overflow: visible')
    expect(dockRule).not.toMatch(/\bbackground(?:-color|-image)?:/)
    expect(dockRule).not.toMatch(/\bbox-shadow:/)

    expect(surfaceRule).toContain('position: absolute')
    expect(surfaceRule).toContain('inset: 30px 0 0')
    expect(surfaceRule).toContain('display: flex')
    expect(surfaceRule).toContain('overflow: visible')
    expect(surfaceRule).toContain('background: #fffdfd')
    expect(surfaceRule).toContain('border-radius: 38px')
  })

  it('用绝对定位抬升选中圆座，不再借助负 margin 或布局属性动画', () => {
    const dockRule = getRule('.root-tab-bar__dock')
    const surfaceRule = getRule('.root-tab-bar__surface')
    const itemRule = getRule('.root-tab-bar__item')
    const iconSeatRule = getRule('.root-tab-bar__icon-seat')
    const selectedSeatRule = getRule('.root-tab-bar__icon-seat--selected')
    const labelRule = getRule('.root-tab-bar__label')

    expect(iconSeatRule).toContain('position: absolute')
    expect(selectedSeatRule).toContain('top: -28px')
    expect(selectedSeatRule).toContain('width: 86px')
    expect(selectedSeatRule).toContain('height: 86px')
    expect(css).not.toMatch(/\bmargin(?:-(?:top|right|bottom|left))?:\s*-\d/)

    const transitions = Array.from(css.matchAll(/\btransition:\s*([^;]+);/g), (match) => match[1])
    expect(transitions.length).toBeGreaterThan(0)
    for (const transition of transitions) {
      expect(transition).not.toMatch(/\b(?:width|height|margin|top|right|bottom|left)\b/)
    }
    expect(css).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.root-tab-bar__item:active \.root-tab-bar__icon-seat,[\s\S]*?\.root-tab-bar__item--selected:active \.root-tab-bar__icon-seat\s*\{[^}]*transform: translateX\(-50%\)/,
    )

    const dockHeight = pixels(dockRule, 'height')
    const surfaceTop = pixels(surfaceRule, 'inset')
    const selectedTop = pixels(selectedSeatRule, 'top')
    const selectedHeight = pixels(selectedSeatRule, 'height')
    const itemBottomPadding = trailingPaddingPixels(itemRule)
    const labelHeight = pixels(labelRule, 'font-size') * unitless(labelRule, 'line-height')
    const selectedTopInDock = surfaceTop + selectedTop
    const selectedBottomInDock = selectedTopInDock + selectedHeight
    const labelTopInDock = dockHeight - itemBottomPadding - labelHeight

    expect(dockHeight - surfaceTop).toBe(128)
    expect(selectedTopInDock).toBeGreaterThanOrEqual(0)
    expect(selectedBottomInDock).toBeLessThanOrEqual(dockHeight)
    expect(labelTopInDock - selectedBottomInDock).toBeGreaterThanOrEqual(16)
  })
})

function getRule(selector: string): string {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = css.match(new RegExp(`${escapedSelector}\\s*\\{([^}]*)\\}`))

  expect(match).not.toBeNull()
  return match?.[1] ?? ''
}

function pixels(rule: string, property: string): number {
  const match = rule.match(new RegExp(`${property}:\\s*(-?\\d+(?:\\.\\d+)?)px`))
  expect(match).not.toBeNull()
  return Number(match?.[1])
}

function unitless(rule: string, property: string): number {
  const match = rule.match(new RegExp(`${property}:\\s*(\\d+(?:\\.\\d+)?)`))
  expect(match).not.toBeNull()
  return Number(match?.[1])
}

function trailingPaddingPixels(rule: string): number {
  const match = rule.match(/padding:\s*0\s+\d+(?:\.\d+)?px\s+(\d+(?:\.\d+)?)px/)
  expect(match).not.toBeNull()
  return Number(match?.[1])
}
