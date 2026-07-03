'use strict';

const mongoose = require('mongoose');

async function connectDB(uri) {
  mongoose.set('debug', (collection, method, query, doc) => {
    console.log(`[mongo] ${collection}.${method}`, JSON.stringify(query), doc ? JSON.stringify(doc) : '');
  });

  await mongoose.connect(uri);
  console.log(`[mongo] connected to ${uri}`);
}

module.exports = { connectDB };
