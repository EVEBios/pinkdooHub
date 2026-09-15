const babelJest = require('babel-jest')

// Taro 官方 transformer 未启用私有方法/属性插件，而 Jest 自身（jest-runner）等
// node_modules 文件包含 #private method，全量转译时会报错；这里在相同预设上补齐
// （Spike 结论）。
module.exports = babelJest.createTransformer({
  presets: [
    ['taro', { framework: 'react', ts: true }],
    ['@babel/preset-env', { modules: 'commonjs' }],
    ['@babel/preset-react'],
    '@babel/preset-typescript'
  ],
  plugins: [
    '@babel/plugin-transform-private-methods',
    '@babel/plugin-transform-class-properties'
  ]
})
