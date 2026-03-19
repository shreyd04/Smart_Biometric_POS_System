import axios from "axios";
import ApiError from "../utility/ApiError.js";

const BIO_BASE = process.env.BIOMETRIC_BASE || "http://localhost:5001";

export const verifyBiometric = async ({ userId, imageBase64, imagesBase64 }) => {
  try {
    const payload = { user_id: userId };
    
    if (imagesBase64 && imagesBase64.length > 0) {
      payload.images_base64 = imagesBase64;
    } else if (imageBase64) {
      payload.image_base64 = imageBase64;
    }
    
    const res = await axios.post(`${BIO_BASE}/verify`, payload);
    const data = res.data;

    if (!data || typeof data.biometric_confidence !== "number") {
      throw new Error("Invalid biometric service response");
    }

    return data;
  } catch (error) {
    throw new ApiError(502, `Biometric service unavailable: ${error.message}`);
  }
};
export const enrollBiometric = async ({ userId, imageBase64 }) => {
  try {
    const res = await axios.post(`${BIO_BASE}/enroll`, {
      user_id: userId,
      image_base64: imageBase64
    });
    return res.data;
  } catch (error) {
    const message = error.response?.data?.message || error.message;
    throw new ApiError(502, `Enrollment service error: ${message}`);
  }
};
