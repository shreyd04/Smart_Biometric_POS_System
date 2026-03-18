// backend/services/ml.service.js
import axios from "axios";
import ApiError from "../utility/ApiError.js";

const ML_BASE = process.env.ML_BASE || "http://localhost:5000";

export const predictFraud = async (features) => {
  try {
    const response = await axios.post(`${ML_BASE}/predict`, features);
    if (
      typeof response.data?.fraud_score !== "number" ||
      !response.data?.risk_label
    ) {
      throw new Error("Invalid ML response");
    }
    return response.data;
  } catch (error) {
    throw new ApiError(502, `ML service unavailable: ${error.message}`);
  }
};