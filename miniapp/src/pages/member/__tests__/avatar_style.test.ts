import { join } from 'node:path'

import { compile } from 'sass'

const stylesheet = join(__dirname, '..', 'index.scss')

describe('会员头像占位字母布局', () => {
  const css = compile(stylesheet).css

  function declarationsFor(selector: string): string {
    const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const match = css.match(new RegExp(`${escapedSelector}\\s*\\{([^}]*)\\}`))
    if (!match) throw new Error(`${selector} rule not found`)
    return match[1]
  }

  it('使用完整圆形区域双轴居中字母，并消除默认行高偏移', () => {
    const avatar = declarationsFor('.member-profile__avatar')
    const fallback = declarationsFor('.member-profile__avatar--fallback')
    const initial = declarationsFor('.member-profile__avatar-initial')

    expect(avatar).toContain('box-sizing: border-box')
    expect(fallback).toContain('position: relative')
    expect(initial).toContain('position: absolute')
    expect(initial).toContain('inset: 0')
    expect(initial).toContain('display: flex')
    expect(initial).toContain('align-items: center')
    expect(initial).toContain('justify-content: center')
    expect(initial).toContain('line-height: 1')
    expect(initial).toContain('text-align: center')
    expect(initial).toContain('transform: translateY(-1px)')
  })
})
