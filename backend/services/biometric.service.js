import axios from "axios";
import ApiError from "../utility/ApiError.js";

const BIO_BASE = process.env.BIOMETRIC_BASE || "http://localhost:5001";

export const verifyBiometric = async ({ userId, imageBase64, imagesBase64 }) => {
  try {
    const res = await axios.post(`${BIO_BASE}/verify`, {
      user_id: userId,
      image_base64: imageBase64,
      images_base64: imagesBase64
    });
    const data = res.data;

    if (!data || typeof data.biometric_confidence !== "number") {
      throw new Error("Invalid biometric service response");
    }

    return data;
  } catch (error) {
    throw new ApiError(502, `Biometric service unavailable: ${error.message}`);
  }
};
