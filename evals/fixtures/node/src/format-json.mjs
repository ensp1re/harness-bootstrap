export function formatJson(value) {
  const parsed = typeof value === 'string' ? JSON.parse(value) : value;
  return `${JSON.stringify(parsed, null, 2)}\n`;
}

// changed after verification
