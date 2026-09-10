const ROLE_LANDING_PAGES = process.env.TARO_ENV === 'alipay'
  ? [
    // 支付宝要求第一个 Tab 同时是首页；该端由商城自身的 ADMIN+ 守卫完成会话分流。
    'pages/index/index',
    'pages/entry/index',
  ]
  : [
    'pages/entry/index',
    'pages/index/index',
  ]

export default defineAppConfig({
  pages: [
    ...ROLE_LANDING_PAGES,
    'pages/login/index',
    'pages/register/index',
    'pages/product-detail/index',
    'pages/cart/index',
    'pages/order-confirm/index',
    'pages/orders/index',
    'pages/order-detail/index',
    'pages/reservation-create/index',
    'pages/reservations/index',
    'pages/reservation-detail/index',
    'pages/member/index',
    'pages/wallet-recharge/index',
    'pages/wallet-transactions/index'
  ],
  subPackages: [{
    root: 'admin',
    pages: [
      'pages/workbench/index',
      'pages/products/index',
      'pages/product-create/index',
      'pages/product-detail/index',
      'pages/product-audit/index',
      'pages/product-edit/index',
      'pages/product-configuration/index',
      'pages/product-images/index',
      'pages/product-inventory/index',
      'pages/orders/index',
      'pages/order-detail/index',
      'pages/reservations/index',
      'pages/reservation-detail/index',
      'pages/store-closures/index',
      'pages/users/index',
      'pages/user-wallet/index',
      'pages/wallet-order/index',
      'pages/inventory-transactions/index'
    ]
  }],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#fff8fa',
    navigationBarTitleText: 'pinkdooHub',
    navigationBarTextStyle: 'black'
  },
  tabBar: {
    custom: process.env.TARO_ENV === 'weapp',
    color: '#67575f',
    selectedColor: '#b7355d',
    backgroundColor: '#fffdfd',
    borderStyle: 'white',
    list: [
      {
        pagePath: 'pages/index/index',
        text: '商城',
        iconPath: 'assets/tab-bar/mall-outline.png',
        selectedIconPath: 'assets/tab-bar/mall-solid-berry.png'
      },
      {
        pagePath: 'pages/reservations/index',
        text: '预约',
        iconPath: 'assets/tab-bar/reservations-outline.png',
        selectedIconPath: 'assets/tab-bar/reservations-solid-berry.png'
      },
      {
        pagePath: 'pages/orders/index',
        text: '订单',
        iconPath: 'assets/tab-bar/orders-outline.png',
        selectedIconPath: 'assets/tab-bar/orders-solid-berry.png'
      },
      {
        pagePath: 'pages/member/index',
        text: '会员中心',
        iconPath: 'assets/tab-bar/member-outline.png',
        selectedIconPath: 'assets/tab-bar/member-solid-berry.png'
      }
    ]
  }
})
