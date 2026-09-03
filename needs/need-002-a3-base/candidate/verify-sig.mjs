// candidate/verify-sig.mjs
// Implements the `verify-sig` class of the Warrant contract.
// Uses Node.js built-ins only. No network, no child processes, no external packages.

import { createPublicKey, verify } from 'node:crypto';

// Ed25519 group order L
const L = 2n ** 252n + 2777552093292854368n;

// 8 canonical torsion point encodings (small-order public keys)
// These are the 8 points of order 1, 2, 4, 8 in the 2-torsion subgroup
const TORSION_KEYS = new Set([
  '0000000000000000000000000000000000000000000000000000000000000000',
  '0100000000000000000000000000000000000000000000000000000000000000',
  '0000000000000000000000000000000000000000000000000000000000000080',
  'ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f',
  'c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a',
  '26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05',
  '26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85',
  'c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa',
]);

// Additional non-canonical encodings that must be rejected
// These have y >= p (after clearing sign bit) or other non-canonical forms
const NON_CANONICAL_KEYS = new Set([
  '0100000000000000000000000000000000000000000000000000000000000080',
  'ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff',
  'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff',
]);

// Domain separator: "warrant-sig-v1:" (15 bytes)
const SEPARATOR = 'warrant-sig-v1:';

// SPKI prefix for Ed25519 public key (DER encoding of SubjectPublicKeyInfo)
// This is the standard 12-byte prefix for Ed25519 in PKCS#8/SPKI format
const SPKI_PREFIX = Buffer.from('302a300506032b6570032100', 'hex');

function hexToBytes(hex) {
  if (typeof hex !== 'string') return null;
  if (hex.length % 2 !== 0) return null;
  // Check for valid hex characters
  if (!/^[0-9a-f]+$/.test(hex)) return null;
  try {
    return Buffer.from(hex, 'hex');
  } catch {
    return null;
  }
}

function isWeakKey(keyHex) {
  // Check if key is in the torsion blocklist
  if (TORSION_KEYS.has(keyHex)) return true;
  if (NON_CANONICAL_KEYS.has(keyHex)) return true;
  
  // Check if key is non-canonical: y >= p after clearing sign bit
  // p = 2^255 - 19
  const p = 2n ** 255n - 19n;
  const keyBytes = hexToBytes(keyHex);
  if (!keyBytes || keyBytes.length !== 32) return true;
  
  // Clear the sign bit (bit 255, i.e., the high bit of the last byte)
  const yBytes = Buffer.from(keyBytes);
  yBytes[31] &= 0x7f;
  
  // Convert to BigInt (little-endian for Ed25519 encoding)
  let y = 0n;
  for (let i = 31; i >= 0; i--) {
    y = (y << 8n) | BigInt(yBytes[i]);
  }
  
  // If y >= p, it's non-canonical
  if (y >= p) return true;
  
  return false;
}

function checkSignatureCanonical(sigHex) {
  // Check if S scalar is canonical (S < L)
  const sigBytes = hexToBytes(sigHex);
  if (!sigBytes || sigBytes.length !== 64) return false;
  
  // S is the last 32 bytes of the signature
  let s = 0n;
  for (let i = 63; i >= 32; i--) {
    s = (s << 8n) | BigInt(sigBytes[i]);
  }
  
  // S must be < L
  if (s >= L) return false;
  
  return true;
}

export function handle(className, input) {
  if (className !== 'verify-sig') {
    return { unsupported: `class ${className} is not handled by verify-sig` };
  }
  
  try {
    const { warrant_id, key, sig } = input;
    
    // Validate inputs
    if (typeof warrant_id !== 'string' || typeof key !== 'string' || typeof sig !== 'string') {
      return { output: { valid: false } };
    }
    
    // Check key length (must be 32 bytes = 64 hex chars)
    if (key.length !== 64) {
      return { output: { valid: false } };
    }
    
    // Check signature length (must be 64 bytes = 128 hex chars)
    if (sig.length !== 128) {
      return { output: { valid: false } };
    }
    
    // Check warrant_id length (must be 32 bytes = 64 hex chars)
    if (warrant_id.length !== 64) {
      return { output: { valid: false } };
    }
    
    // Check for weak/non-canonical key
    if (isWeakKey(key)) {
      return { output: { valid: false } };
    }
    
    // Check signature canonicality (S < L)
    if (!checkSignatureCanonical(sig)) {
      return { output: { valid: false } };
    }
    
    // Construct the message: "warrant-sig-v1:" || WarrantID_raw (32 bytes)
    const separatorBytes = Buffer.from(SEPARATOR, 'ascii');
    const warrantIdBytes = hexToBytes(warrant_id);
    if (!warrantIdBytes || warrantIdBytes.length !== 32) {
      return { output: { valid: false } };
    }
    
    const message = Buffer.concat([separatorBytes, warrantIdBytes]);
    
    // Construct the public key in SPKI format for Node.js crypto
    const keyBytes = hexToBytes(key);
    if (!keyBytes || keyBytes.length !== 32) {
      return { output: { valid: false } };
    }
    
    const spkiKey = Buffer.concat([SPKI_PREFIX, keyBytes]);
    
    // Create public key object
    let publicKey;
    try {
      publicKey = createPublicKey({
        key: spkiKey,
        format: 'der',
        type: 'spki'
      });
    } catch {
      return { output: { valid: false } };
    }
    
    // Verify the signature
    const sigBytes = hexToBytes(sig);
    if (!sigBytes || sigBytes.length !== 64) {
      return { output: { valid: false } };
    }
    
    try {
      const valid = verify(null, message, publicKey, sigBytes);
      return { output: { valid: valid } };
    } catch {
      return { output: { valid: false } };
    }
  } catch {
    return { output: { valid: false } };
  }
}
