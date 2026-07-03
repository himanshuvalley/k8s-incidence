'use strict';

require('dotenv').config();

const express = require('express');
const { connectDB } = require('./db');
const { getMongoUri } = require('./memory-db');
const { seedDatabase } = require('./seed-data');
const User = require('./models/User');
const apiRouter = require('./routes/api');
const authRouter = require('./routes/auth');

const PORT = process.env.PORT || 3000;

const app = express();

app.use(express.json());

app.use((req, res, next) => {
  const start = Date.now();
  res.on('finish', () => {
    console.log(`[http] ${req.method} ${req.originalUrl} ${res.statusCode} ${Date.now() - start}ms`);
  });
  next();
});

app.use('/api/auth', authRouter);
app.use('/api', apiRouter);

app.get('/', (req, res) => {
  res.json({
    message: 'Trace Test API',
    docs: '/api/timing-reference',
    traceVerification: 'TRACE_VERIFICATION.md',
    endpoints: {
      timingReference: '/api/timing-reference',
      statusCodes: '/api/status/{200|201|204|400|401|403|404|409|422|429|500|503}',
      delays: '/api/delay/{ms} | /api/delay/random',
      users: '/api/users | /api/users/slow | /api/users/:id',
      products: '/api/products | /api/products/slow/aggregation',
      orders: '/api/orders | /api/orders/slow | /api/dashboard',
      errors: '/api/crash',
    },
  });
});

app.use((err, req, res, _next) => {
  console.error('[error]', err.message);
  res.status(500).json({ error: 'Internal Server Error', message: err.message });
});

async function main() {
  const mongoUri = await getMongoUri();
  await connectDB(mongoUri);

  const userCount = await User.countDocuments();
  if (userCount === 0) {
    console.log('[seed] empty database — seeding...');
    await seedDatabase({ clear: false });
  }
  app.listen(PORT, () => {
    console.log(`[server] listening on http://localhost:${PORT}`);
  });
}

main().catch((err) => {
  console.error('[fatal]', err);
  process.exit(1);
});
