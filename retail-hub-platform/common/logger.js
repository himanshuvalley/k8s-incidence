function log(service, level, message, meta = {}) {
  console.log(
    JSON.stringify({
      timestamp: new Date().toISOString(),
      level,
      service,
      message,
      ...meta,
    })
  );
}

module.exports = { log };
