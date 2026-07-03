'use strict';

require('dotenv').config();
const mongoose = require('mongoose');
const { getMongoUri } = require('./memory-db');
const { seedDatabase } = require('./seed-data');

async function seed() {
  const mongoUri = await getMongoUri();
  await mongoose.connect(mongoUri);
  console.log('[seed] connected');

  await seedDatabase();
  await mongoose.disconnect();
  console.log('[seed] done');
}

seed().catch((err) => {
  console.error('[seed] failed', err);
  process.exit(1);
});
