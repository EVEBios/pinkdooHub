export default defineAppConfig({
  pages: [
    'pages/index/index',
    'pages/login/index',
    'pages/product-detail/index',
    'pages/cart/index',
    'pages/order-confirm/index',
    'pages/orders/index',
    'pages/order-detail/index'
  ],
  subPackages: [{
    root: 'admin',
    pages: [
      'pages/orders/index',
      'pages/order-detail/index'
    ]
  }],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#fff',
    navigationBarTitleText: 'pinkdooHub',
    navigationBarTextStyle: 'black'
  }
})
