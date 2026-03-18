import axios from "axios";

export const verifyBiometric = async (userId) => {
  try {
    const res = await axios.get(
      `http://localhost:5001/verify/${userId}`
    );

    return res.data;

  } catch (error) {
    return {
      biometric_confidence: 0,
      hash: null,
      features:[]
    };
  }
};