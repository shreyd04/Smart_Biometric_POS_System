export const evaluateTransaction = ({
  biometric_confidence,
  fraud_score
}) => {

  // biometric check
  if (biometric_confidence < 0.75) {
    return {
      allowed: false,
      reason: "Biometric failed"
    };
  }

  // fraud check
  if (fraud_score > 0.8) {
    return {
      allowed: true,
      status: "pending",
      reason: "High fraud risk"
    };
  }

  // safe transaction
  return {
    allowed: true,
    status: "completed"
  };
};