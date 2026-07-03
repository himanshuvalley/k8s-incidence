'use strict';

const express = require('express');
const User = require('../models/User');
const Product = require('../models/Product');
const Order = require('../models/Order');
const { TIMING_REFERENCE, MULTI_DB_ENDPOINTS, timingMeta } = require('../timing-reference');

const router = express.Router();

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function timed(label, fn) {
  return async (req, res, next) => {
    const start = Date.now();
    const setTimingHeader = () => {
      if (!res.headersSent) {
        res.setHeader('X-Response-Time', `${Date.now() - start}ms`);
      }
    };
    const wrap = (method) => {
      const original = res[method].bind(res);
      res[method] = (...args) => {
        setTimingHeader();
        return original(...args);
      };
    };
    wrap('json');
    wrap('send');
    wrap('end');
    res.on('finish', () => {
      console.log(`[timing] ${req.method} ${req.originalUrl} → ${Date.now() - start}ms (${label})`);
    });
    try {
      await fn(req, res, next);
    } catch (err) {
      next(err);
    }
  };
}

// ── Health ──────────────────────────────────────────────────────────────────

router.get('/health', (req, res) => {
  res.json({ status: 'ok', uptime: process.uptime(), timing: timingMeta('/api/health', 0) });
});

router.get('/timing-reference', (req, res) => {
  res.json({
    description: 'Expected response times and DB call counts for all endpoints. Compare with X-Response-Time header.',
    endpoints: TIMING_REFERENCE,
    multiDbEndpoints: MULTI_DB_ENDPOINTS,
  });
});

// ── Status code endpoints (no DB) ───────────────────────────────────────────

router.get('/status/200', (req, res) => {
  res.status(200).json({ message: 'OK' });
});

router.get('/status/201', (req, res) => {
  res.status(201).json({ message: 'Created' });
});

router.get('/status/204', (req, res) => {
  res.status(204).end();
});

router.get('/status/400', (req, res) => {
  res.status(400).json({ error: 'Bad Request', code: 'BAD_REQUEST' });
});

router.get('/status/401', (req, res) => {
  res.status(401).json({ error: 'Unauthorized', code: 'UNAUTHORIZED' });
});

router.get('/status/403', (req, res) => {
  res.status(403).json({ error: 'Forbidden', code: 'FORBIDDEN' });
});

router.get('/status/404', (req, res) => {
  res.status(404).json({ error: 'Not Found', code: 'NOT_FOUND' });
});

router.get('/status/409', (req, res) => {
  res.status(409).json({ error: 'Conflict', code: 'CONFLICT' });
});

router.get('/status/422', (req, res) => {
  res.status(422).json({ error: 'Unprocessable Entity', code: 'VALIDATION_ERROR' });
});

router.get('/status/429', (req, res) => {
  res.status(429).json({ error: 'Too Many Requests', code: 'RATE_LIMITED' });
});

router.get('/status/500', (req, res) => {
  res.status(500).json({ error: 'Internal Server Error', code: 'INTERNAL_ERROR' });
});

router.get('/status/503', (req, res) => {
  res.status(503).json({ error: 'Service Unavailable', code: 'SERVICE_UNAVAILABLE' });
});

// ── Artificial delay (no DB) ────────────────────────────────────────────────

router.get(
  '/delay/:ms',
  timed('artificial-delay', async (req, res) => {
    const ms = Math.min(parseInt(req.params.ms, 10) || 0, 30000);
    await sleep(ms);
    res.json({
      delayed: ms,
      timing: { expectedMs: ms, artificialDelayMs: ms, notes: 'Exact delay — response time should match this value' },
    });
  })
);

router.get(
  '/delay/random',
  timed('random-delay', async (req, res) => {
    const ms = Math.floor(Math.random() * 3000) + 100;
    await sleep(ms);
    res.json({
      delayed: ms,
      timing: { expectedMs: '100–3100', artificialDelayMs: ms, notes: 'Actual delay returned in delayed field' },
    });
  })
);

// ── Users (MongoDB) ─────────────────────────────────────────────────────────

router.get(
  '/users',
  timed('users-find-all', async (req, res) => {
    const users = await User.find().limit(50).lean();
    res.json({ count: users.length, data: users });
  })
);

router.get(
  '/users/slow',
  timed('users-slow-query', async (req, res) => {
    // Regex scan without index — intentionally slow on large datasets
    await sleep(200);
    const users = await User.find({ name: /user/i }).sort({ createdAt: -1 }).lean();
    res.json({ count: users.length, data: users, timing: timingMeta('/api/users/slow', 200, '200ms sleep + regex scan + sort') });
  })
);

router.get(
  '/users/:id',
  timed('users-find-by-id', async (req, res) => {
    const user = await User.findById(req.params.id).lean();
    if (!user) {
      return res.status(404).json({ error: 'User not found' });
    }
    res.json({ data: user });
  })
);

router.post(
  '/users',
  timed('users-create', async (req, res) => {
    const { name, email, role } = req.body;
    if (!name || !email) {
      return res.status(400).json({ error: 'name and email are required' });
    }
    try {
      const user = await User.create({ name, email, role });
      res.status(201).json({ data: user });
    } catch (err) {
      if (err.code === 11000) {
        return res.status(409).json({ error: 'Email already exists' });
      }
      throw err;
    }
  })
);

router.get(
  '/users/search/by-role/:role',
  timed('users-aggregate-by-role', async (req, res) => {
    const result = await User.aggregate([
      { $match: { role: req.params.role, active: true } },
      { $group: { _id: '$role', count: { $sum: 1 }, names: { $push: '$name' } } },
    ]);
    res.json({ data: result });
  })
);

// ── Products (MongoDB) ──────────────────────────────────────────────────────

router.get(
  '/products',
  timed('products-find', async (req, res) => {
    const { category, minPrice } = req.query;
    const filter = {};
    if (category) filter.category = category;
    if (minPrice) filter.price = { $gte: Number(minPrice) };
    const products = await Product.find(filter).sort({ price: -1 }).limit(100).lean();
    res.json({ count: products.length, data: products });
  })
);

router.get(
  '/products/slow/aggregation',
  timed('products-slow-aggregation', async (req, res) => {
    await sleep(300);
    const result = await Product.aggregate([
      { $group: { _id: '$category', avgPrice: { $avg: '$price' }, totalStock: { $sum: '$stock' }, count: { $sum: 1 } } },
      { $sort: { avgPrice: -1 } },
    ]);
    res.json({ data: result, timing: timingMeta('/api/products/slow/aggregation', 300, '300ms sleep + full collection $group') });
  })
);

// ── Orders (MongoDB with populate — multi-query) ─────────────────────────────

router.get(
  '/orders',
  timed('orders-with-populate', async (req, res) => {
    const orders = await Order.find()
      .populate('userId', 'name email')
      .populate('productIds', 'name price')
      .sort({ createdAt: -1 })
      .limit(20)
      .lean();
    res.json({ count: orders.length, data: orders });
  })
);

router.get(
  '/orders/slow',
  timed('orders-slow-join', async (req, res) => {
    await sleep(150);
    const orders = await Order.aggregate([
      { $lookup: { from: 'users', localField: 'userId', foreignField: '_id', as: 'user' } },
      { $lookup: { from: 'products', localField: 'productIds', foreignField: '_id', as: 'products' } },
      { $unwind: '$user' },
      { $match: { status: 'pending' } },
      { $project: { total: 1, status: 1, userName: '$user.name', productCount: { $size: '$products' } } },
      { $limit: 50 },
    ]);
    res.json({ count: orders.length, data: orders, timing: timingMeta('/api/orders/slow', 150, '150ms sleep + $lookup joins') });
  })
);

router.post(
  '/orders',
  timed('orders-create', async (req, res) => {
    const { userId, productIds, total } = req.body;
    if (!userId || !productIds?.length || total == null) {
      return res.status(400).json({ error: 'userId, productIds, and total are required' });
    }
    const user = await User.findById(userId);
    if (!user) {
      return res.status(404).json({ error: 'User not found' });
    }
    const order = await Order.create({ userId, productIds, total });
    res.status(201).json({ data: order });
  })
);

// ── Chained slow endpoint (multiple DB round-trips) ─────────────────────────

router.get(
  '/dashboard',
  timed('dashboard-chained', async (req, res) => {
    const [userCount, productCount, recentOrders] = await Promise.all([
      User.countDocuments({ active: true }),
      Product.countDocuments(),
      Order.find().sort({ createdAt: -1 }).limit(5).populate('userId', 'name').lean(),
    ]);
    await sleep(100);
    const topCategories = await Product.aggregate([
      { $group: { _id: '$category', revenue: { $sum: '$price' } } },
      { $sort: { revenue: -1 } },
      { $limit: 5 },
    ]);
    res.json({
      stats: { users: userCount, products: productCount, orders: recentOrders.length },
      recentOrders,
      topCategories,
      timing: timingMeta('/api/dashboard', 100, '3 parallel queries + 100ms sleep + aggregation'),
    });
  })
);

// ── Intentional server error (throws) ───────────────────────────────────────

router.get('/crash', () => {
  throw new Error('Intentional unhandled error for trace testing');
});

module.exports = router;
