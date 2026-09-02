export default defineAppConfig({
  pages: [
    'pages/index/index',
    'pages/login/index',
    'pages/register/index',
    'pages/product-detail/index',
    'pages/cart/index',
    'pages/order-confirm/index',
    'pages/orders/index',
    'pages/order-detail/index'
  ],
  subPackages: [{
    root: 'admin',
    pages: [
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
      'pages/users/index',
      'pages/inventory-transactions/index'
    ]
  }],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#fff',
    navigationBarTitleText: 'pinkdooHub',
    navigationBarTextStyle: 'black'
  }
})
