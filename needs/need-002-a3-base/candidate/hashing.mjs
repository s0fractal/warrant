// hashing.mjs
// Warrant conformance class module for: blob-hash, sig-message
// Node.js built-ins only. No network, no child processes, no external packages.

import { createHash } from 'node:crypto';

/**
 * @param {string} className - The conformance class to handle.
 * @param {object} input - The input object for the class.
 * @returns {Promise<{output: object} | {unsupported: string}>}
 */
export async function handle(className, input) {
  if (className === 'blob-hash') {
    try {
      if (!input || typeof input !== 'object' || Array.isArray(input)) {
        return { unsupported: 'input must be an object' };
      }
      const b64 = input.bytes_base64;
      if (typeof b64 !== 'string') {
        return { unsupported: 'bytes_base64 must be a string' };
      }
      // Decode base64 to raw bytes
      const bytes = Buffer.from(b64, 'base64');
      // Compute SHA-256 over the raw bytes
      const hash = createHash('sha256').update(bytes).digest('hex');
      // Ensure lowercase hex (digest('hex') already returns lowercase)
      return { output: { hash } };
    } catch (e) {
      return { unsupported: `blob-hash failed: ${e.message}` };
    }
  }

  if (className === 'sig-message') {
    try {
      if (!input || typeof input !== 'object' || Array.isArray(input)) {
        return { unsupported: 'input must be an object' };
      }
      const warrantId = input.warrant_id;
      if (typeof warrantId !== 'string') {
        return { output: { error: 'warrant_id must be a string' } };
      }
      // Validate: exactly 64 lowercase hex characters
      // Lowercase hex: [0-9a-f]
      if (warrantId.length !== 64) {
        return { output: { error: `warrant_id must be 64 hex characters, got ${warrantId.length}` } };
      }
      if (!/^[0-9a-f]{64}$/.test(warrantId)) {
        return { output: { error: 'warrant_id must be lowercase hex with no prefix or separators' } };
      }
      // Hex-decode the 64-char string to 32 raw bytes
      const rawBytes = Buffer.from(warrantId, 'hex');
      // Sanity check: should be exactly 32 bytes
      if (rawBytes.length !== 32) {
        return { output: { error: 'warrant_id did not decode to 32 bytes' } };
      }
      // Build the 47-byte message:
      // 15 ASCII bytes of "warrant-sig-v1:" followed by 32 raw bytes
      const separator = Buffer.from('warrant-sig-v1:', 'ascii');
      // Verify separator is exactly 15 bytes
      if (separator.length !== 15) {
        return { unsupported: 'internal error: separator length mismatch' };
      }
      const message = Buffer.concat([separator, rawBytes]);
      // Verify total is 47 bytes
      if (message.length !== 47) {
        return { unsupported: 'internal error: message length mismatch' };
      }
      // Output the hex of the exact 47 bytes
      const messageHex = message.toString('hex');
      return { output: { message_hex: messageHex } };
    } catch (e) {
      return { output: { error: `sig-message failed: ${e.message}` } };
    }
  }

  return { unsupported: `unknown class: ${className}` };
}
