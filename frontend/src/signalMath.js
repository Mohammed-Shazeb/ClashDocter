const fmt = (value, digits = 3) =>
  value === null || value === undefined ? 'n/a' : value.toFixed(digits);

// Three decimals everywhere: at two, the parts shown do not add up to the score
// shown, which reads as an arithmetic error in a panel whose job is arithmetic.
export const signalMath = (signal) =>
  `${fmt(signal.jaccard)} × ${fmt(signal.normalized_weight)} = +${fmt(signal.contribution)}`;
