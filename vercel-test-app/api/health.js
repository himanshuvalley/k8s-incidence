module.exports = (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  res.status(200).json({
    status: 'ok',
    service: 'vercel-test-app',
    timestamp: new Date().toISOString(),
    region: process.env.VERCEL_REGION || 'local',
    deployment: process.env.VERCEL_URL || 'localhost',
  });
};
