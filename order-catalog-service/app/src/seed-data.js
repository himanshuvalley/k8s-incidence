'use strict';

const User = require('./models/User');
const Product = require('./models/Product');
const Order = require('./models/Order');

const CATEGORIES = ['electronics', 'books', 'clothing', 'food', 'sports'];
const ROLES = ['user', 'admin'];

async function seedDatabase({ clear = true } = {}) {
  if (clear) {
    await Promise.all([User.deleteMany({}), Product.deleteMany({}), Order.deleteMany({})]);
    console.log('[seed] cleared collections');
  }

  const users = [];
  for (let i = 1; i <= 200; i++) {
    users.push({
      name: `User ${i}`,
      email: `user${i}@example.com`,
      role: ROLES[i % 10 === 0 ? 1 : 0],
      active: i % 7 !== 0,
    });
  }
  const createdUsers = await User.insertMany(users);
  console.log(`[seed] inserted ${createdUsers.length} users`);

  const products = [];
  for (let i = 1; i <= 500; i++) {
    products.push({
      name: `Product ${i}`,
      category: CATEGORIES[i % CATEGORIES.length],
      price: Math.round((Math.random() * 500 + 5) * 100) / 100,
      stock: Math.floor(Math.random() * 200),
    });
  }
  const createdProducts = await Product.insertMany(products);
  console.log(`[seed] inserted ${createdProducts.length} products`);

  const orders = [];
  for (let i = 0; i < 150; i++) {
    const user = createdUsers[i % createdUsers.length];
    const numProducts = Math.floor(Math.random() * 4) + 1;
    const productIds = [];
    let total = 0;
    for (let j = 0; j < numProducts; j++) {
      const p = createdProducts[(i * 3 + j) % createdProducts.length];
      productIds.push(p._id);
      total += p.price;
    }
    orders.push({
      userId: user._id,
      productIds,
      total: Math.round(total * 100) / 100,
      status: ['pending', 'shipped', 'delivered', 'cancelled'][i % 4],
    });
  }
  const createdOrders = await Order.insertMany(orders);
  console.log(`[seed] inserted ${createdOrders.length} orders`);
}

module.exports = { seedDatabase };
