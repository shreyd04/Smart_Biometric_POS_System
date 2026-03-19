import {
    registerUser,
    loginUser,
    logout,
    getAllUsers,
    getUserById,
    deleteUserById,
    updateUserById,
    
} from "../controllers/user.controllers.js";

import { authorizeRoles } from "../middleware/permissions.middleware.js";
import { verifyJWT } from "../middleware/auth.middleware.js";
import express from "express";

const router = express.Router();

router.post("/register", registerUser);
router.post("/login", loginUser);

router.use(verifyJWT); 

router.post("/logout", logout);

router.get("/", authorizeRoles("admin"), getAllUsers);
router.get("/:id", authorizeRoles("admin"), getUserById);
router.put("/:id", authorizeRoles("admin"), updateUserById);
router.delete("/:id", authorizeRoles("admin"), deleteUserById);

export default router;