'use strict';

const mongoose = require('mongoose');

const userSchema = new mongoose.Schema(
  {
    name: { type: String, required: true },
    email: { type: String, required: true, unique: true },
    password: { type: String, select: false },
    role: { type: String, enum: ['user', 'admin'], default: 'user' },
    active: { type: Boolean, default: true },
  },
  { timestamps: true }
);

userSchema.index({ role: 1, active: 1 });

module.exports = mongoose.model('User', userSchema);
