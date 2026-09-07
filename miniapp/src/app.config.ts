export default defineAppConfig({
  pages: [
    'pages/index/index',
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
  }
})
