import mongoose from "mongoose";
import Order from "../models/order.model.js";
import Product from "../models/product.model.js";
import { evaluateTransaction } from "../services/evaluation.service.js";

import ApiError from "../utility/ApiError.js";
import ApiResponse from "../utility/ApiResponse.js";

import { verifyBiometric } from "../services/biometric.service.js";
import { predictFraud } from "../services/ml.service.js";
import blockchainService from "../services/blockchain.service.js";


// cosine similarity (reuse)
const cosineSimilarity = (a, b) => {
  let dot = 0, normA = 0, normB = 0;

  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }

  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
};


export const createOrder = async (req, res, next) => {

  const session = await mongoose.startSession();
  session.startTransaction();

  try {

    const userId = req.user._id;

    const { products } = req.body;

    if (!products || products.length === 0) {
      throw new ApiError(400, "Products required");
    }

    let totalAmount = 0;

    const enrichedProducts = [];

    for (const item of products) {

      const product = await Product.findById(item.productId).session(session);

      if (!product) {
        throw new ApiError(404, "Product not found");
      }

      if (product.stock < item.quantity) {
        throw new ApiError(400, "Insufficient stock");
      }

      product.stock -= item.quantity;
      await product.save({ session });

      totalAmount += product.price * item.quantity;

      enrichedProducts.push({
        productId: product._id,
        quantity: item.quantity
      });
    }


    const user = await User.findById(userId);

    if (!user.isBiometricEnrolled) {
      throw new ApiError(400, "Biometric not enrolled");
    }

    const bioRes = await verifyBiometric(userId);

    const score = cosineSimilarity(
      user.biometric.embedding,
      bioRes.features
    );

    if (score < 0.75) {
      throw new ApiError(401, "Biometric verification failed");
    }


    const fraudRes = await predictFraud({
      amount: totalAmount,
      biometric_confidence: score
    });

    const { fraud_score, risk_label } = fraudRes;
    const decision = evaluateTransaction({
      biometric_confidence: score,
      fraud_score
    });

    if (!decision.allowed) {
      throw new ApiError(401, decision.reason);
    }

    createdOrder.status = decision.status;

    const order = await Order.create([{
      userId,
      products: enrichedProducts,
      totalAmount,
      fraud_score,
      risk_label,
      biometric_confidence: score,
      status: risk_label === "High" ? "pending" : "completed"
    }], { session });

    const createdOrder = order[0];


    await blockchainService.recordTransaction({
      orderId: createdOrder._id,
      userId,
      amount: totalAmount,
      biometric_hash: bioRes.hash,
      fraud_score
    });

    await session.commitTransaction();
    session.endSession();

    return res.status(201).json(
      new ApiResponse(201, "Order created", createdOrder)
    );

  } catch (error) {

    await session.abortTransaction();
    session.endSession();

    next(error);
  }
};

export const getAllOrders = async (req, res, next) => {

  try {

    const orders = await Order.find()
      .populate("userId", "-password")
      .populate("products.productId");

    return new ApiResponse(
      res,
      200,
      "Orders fetched successfully",
      { orders }
    );

  } catch (error) {
    return next(new ApiError(500, "Error fetching orders"));
  }
};



export const getOrderById = async (req, res, next) => {

  try {

    const { id } = req.params;

    const order = await Order.findById(id)
      .populate("userId", "-password")
      .populate("products.productId");

    if (!order) {
      throw new ApiError(404, "Order not found");
    }

    return new ApiResponse(
      res,
      200,
      "Order fetched successfully",
      { order }
    );

  } catch (error) {
    return next(new ApiError(500, error.message));
  }
};



export const updateOrderById = async (req, res, next) => {

  try {

    const { id } = req.params;

    const order = await Order.findByIdAndUpdate(
      id,
      req.body,
      { new: true, runValidators: true }
    );

    if (!order) {
      throw new ApiError(404, "Order not found");
    }

    return new ApiResponse(
      res,
      200,
      "Order updated successfully",
      { order }
    );

  } catch (error) {
    return next(new ApiError(500, error.message));
  }
};



export const deleteOrderById = async (req, res, next) => {

  try {

    const { id } = req.params;

    const order = await Order.findByIdAndDelete(id);

    if (!order) {
      throw new ApiError(404, "Order not found");
    }

    return new ApiResponse(
      res,
      200,
      "Order deleted successfully"
    );

  } catch (error) {
    return next(new ApiError(500, error.message));
  }
};