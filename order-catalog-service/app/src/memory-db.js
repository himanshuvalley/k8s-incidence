'use strict';

const { MongoMemoryServer } = require('mongodb-memory-server');

let memoryServer;

async function getMongoUri() {
  if (process.env.USE_MEMORY_DB === 'true') {
    memoryServer = await MongoMemoryServer.create();
    const uri = memoryServer.getUri('trace_test_db');
    console.log('[mongo] using in-memory database');
    return uri;
  }
  return process.env.MONGODB_URI || 'mongodb://localhost:27017/trace_test_db';
}

async function stopMemoryServer() {
  if (memoryServer) {
    await memoryServer.stop();
  }
}

module.exports = { getMongoUri, stopMemoryServer };
