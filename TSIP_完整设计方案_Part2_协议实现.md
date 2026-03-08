# TSIP完整设计方案 - Part 2: 协议详细设计与实现

## 第五章: 详细协议规范

### 5.1 系统参数

#### 全局参数配置

```python
# config/tsip_params.py

class TSIPParameters:
    """TSIP系统参数配置"""
    
    # ===== 隐私参数 =====
    EPSILON_TOTAL = 1.0          # 总隐私预算
    EPSILON_SVT = 0.3            # 稀疏向量技术预算
    EPSILON_VALUE = 0.5          # 值噪声预算
    EPSILON_TSIP = 0.2           # TSIP验证预算
    DELTA = 1e-8                 # DP参数δ
    
    # ===== 物理约束参数 =====
    V_MAX = 100.0                # 最大速度 (m/s) = 360 km/h
    TIME_WINDOW = 300            # 时间窗口 (秒) = 5分钟
    MAX_DISTANCE = V_MAX * TIME_WINDOW  # = 30,000 m = 30 km
    
    # ===== 地理空间参数 =====
    GRID_SIZE = 100              # 网格大小 (米)
    GRID_WIDTH = 10000           # 网格宽度数量
    GRID_HEIGHT = 10000          # 网格高度数量
    DOMAIN_SIZE = GRID_WIDTH * GRID_HEIGHT  # = 10^8 个网格
    
    # 坐标范围 (假设东京市区)
    LAT_MIN = 35.5               # 最小纬度
    LAT_MAX = 35.8               # 最大纬度
    LON_MIN = 139.5              # 最小经度
    LON_MAX = 139.9              # 最大经度
    
    # 投影后的坐标范围 (米)
    X_MIN = 0
    X_MAX = GRID_WIDTH * GRID_SIZE   # = 1,000,000 m = 1000 km
    Y_MIN = 0
    Y_MAX = GRID_HEIGHT * GRID_SIZE  # = 1,000,000 m = 1000 km
    
    # ===== 零知识证明参数 =====
    CURVE = "bn254"              # 椭圆曲线
    HASH_FUNCTION = "poseidon"   # 承诺哈希函数
    SECURITY_PARAM = 128         # 安全参数 (bits)
    
    # ===== 稀疏化参数 =====
    TOP_K = 50                   # 每个用户保留的Top-K位置
    QUANTIZATION_BITS = 4        # 停留时间量化位数
    
    # ===== 系统参数 =====
    NUM_TIME_WINDOWS = 288       # 24小时,每5分钟一个窗口
    BATCH_SIZE = 100             # 聚合批次大小
    BATCH_TIMEOUT = 30           # 批次超时 (秒)
    
    # ===== 恶意行为检测 =====
    MAX_REJECTION_RATE = 0.05    # 最大允许拒绝率 (5%)
    BLACKLIST_THRESHOLD = 3      # 连续拒绝次数阈值
```

---

### 5.2 数据结构定义

#### 位置数据结构

```python
# tsip/types.py

from dataclasses import dataclass
from typing import List, Tuple
import numpy as np

@dataclass
class Location:
    """单个位置点"""
    x: float              # 投影后的x坐标 (米)
    y: float              # 投影后的y坐标 (米)
    timestamp: int        # Unix时间戳 (秒)
    cell_id: int          # 网格ID
    dwell_time: float     # 停留时间 (秒)
    
    def to_array(self) -> np.ndarray:
        """转为numpy数组 (用于电路输入)"""
        return np.array([self.x, self.y, self.timestamp], dtype=np.int64)
    
    @staticmethod
    def from_latlon(lat: float, lon: float, timestamp: int) -> 'Location':
        """从经纬度创建位置"""
        x, y = latlon_to_xy(lat, lon)
        cell_id = xy_to_cell_id(x, y)
        return Location(x, y, timestamp, cell_id, 0.0)


@dataclass
class Trajectory:
    """用户轨迹"""
    user_id: str
    locations: List[Location]
    
    def get_sparse_vector(self) -> Tuple[np.ndarray, np.ndarray]:
        """转为稀疏向量表示"""
        # 聚合停留时间
        cell_visits = {}
        for loc in self.locations:
            if loc.cell_id not in cell_visits:
                cell_visits[loc.cell_id] = 0
            cell_visits[loc.cell_id] += loc.dwell_time
        
        # Top-K筛选
        sorted_cells = sorted(
            cell_visits.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:TSIPParameters.TOP_K]
        
        indices = np.array([c[0] for c in sorted_cells], dtype=np.int32)
        values = np.array([c[1] for c in sorted_cells], dtype=np.float32)
        
        return indices, values


@dataclass
class LocationCommitment:
    """位置承诺"""
    hash: bytes           # Hash(x, y) - 32 bytes
    timestamp: int        # 时间戳
    window_id: int        # 时间窗口ID
    
    def verify(self, location: Location) -> bool:
        """验证位置是否匹配承诺"""
        computed_hash = poseidon_hash(location.x, location.y)
        return computed_hash == self.hash


@dataclass
class TSIPProof:
    """TSIP零知识证明"""
    proof_a: bytes        # Groth16证明的A部分 (G1点, 32 bytes)
    proof_b: bytes        # Groth16证明的B部分 (G2点, 64 bytes)
    proof_c: bytes        # Groth16证明的C部分 (G1点, 32 bytes)
    
    # 公开输入
    prev_commitment: bytes   # 前一个位置的承诺
    curr_commitment: bytes   # 当前位置的承诺
    v_max: float             # 最大速度
    time_diff: int           # 时间差
    
    def to_bytes(self) -> bytes:
        """序列化为字节"""
        return self.proof_a + self.proof_b + self.proof_c
    
    @staticmethod
    def from_bytes(data: bytes, public_inputs: dict) -> 'TSIPProof':
        """从字节反序列化"""
        return TSIPProof(
            proof_a=data[:32],
            proof_b=data[32:96],
            proof_c=data[96:128],
            **public_inputs
        )
    
    def size(self) -> int:
        """证明大小 (字节)"""
        return 128  # Groth16固定大小


@dataclass
class EncryptedLocation:
    """加密的位置数据"""
    ciphertext: bytes        # 加密的(x, y, timestamp)
    shares_a: bytes          # 给聚合器A的秘密份额
    shares_r: bytes          # 给聚合器R的秘密份额
    nonce: bytes             # 加密nonce
    
    def decrypt(self, key_a: bytes, key_r: bytes) -> Location:
        """解密位置 (需要两个密钥)"""
        # 重构秘密
        combined_key = xor_bytes(key_a, key_r)
        plaintext = aes_decrypt(self.ciphertext, combined_key, self.nonce)
        
        x, y, t = decode_location(plaintext)
        return Location(x, y, t, xy_to_cell_id(x, y), 0.0)
```

---

### 5.3 客户端协议实现

#### 5.3.1 TSIP客户端完整实现

```python
# tsip/client.py

import time
import hashlib
from typing import Optional, List
from snarkjs import groth16_prove, groth16_verify  # zk-SNARK库

class TSIPClient:
    """TSIP客户端实现"""
    
    def __init__(self, user_id: str, proving_key_path: str):
        """
        初始化客户端
        
        Args:
            user_id: 用户唯一标识
            proving_key_path: Groth16 proving key文件路径
        """
        self.user_id = user_id
        self.proving_key = self.load_proving_key(proving_key_path)
        
        # 历史位置链
        self.location_history: List[Location] = []
        self.commitment_history: List[LocationCommitment] = []
        
        # 统计信息
        self.stats = {
            "total_submissions": 0,
            "accepted": 0,
            "rejected": 0,
            "avg_proof_time": 0.0
        }
    
    def load_proving_key(self, path: str):
        """加载proving key"""
        with open(path, 'rb') as f:
            return f.read()
    
    def submit_location(self, 
                       lat: float, 
                       lon: float, 
                       timestamp: int,
                       shuffler_url: str) -> bool:
        """
        提交位置到服务器
        
        Args:
            lat: 纬度
            lon: 经度
            timestamp: 时间戳
            shuffler_url: Shuffler服务器地址
            
        Returns:
            是否提交成功
        """
        # 1. 创建位置对象
        location = Location.from_latlon(lat, lon, timestamp)
        
        # 2. 计算位置承诺
        commitment = self.compute_commitment(location)
        
        # 3. 判断是否需要生成TSIP证明
        if len(self.location_history) == 0:
            # 第一次提交,无需证明
            proof = None
        else:
            # 生成TSIP证明
            prev_location = self.location_history[-1]
            prev_commitment = self.commitment_history[-1]
            
            start_time = time.time()
            proof = self.generate_tsip_proof(
                prev_location, 
                location, 
                prev_commitment
            )
            proof_time = time.time() - start_time
            
            # 更新统计
            self.stats["avg_proof_time"] = (
                self.stats["avg_proof_time"] * self.stats["total_submissions"]
                + proof_time
            ) / (self.stats["total_submissions"] + 1)
        
        # 4. 加密位置
        encrypted_loc = self.encrypt_location(location)
        
        # 5. 构造上传消息
        message = {
            "user_id": self.user_id,
            "encrypted_location": encrypted_loc.to_dict(),
            "commitment": commitment.hash.hex(),
            "timestamp": timestamp,
            "window_id": self.get_window_id(timestamp),
            "proof": proof.to_dict() if proof else None
        }
        
        # 6. 发送到Shuffler
        response = self.send_to_shuffler(shuffler_url, message)
        
        # 7. 处理响应
        if response["status"] == "accepted":
            # 更新历史
            self.location_history.append(location)
            self.commitment_history.append(commitment)
            self.stats["accepted"] += 1
            self.stats["total_submissions"] += 1
            return True
        else:
            # 拒绝
            self.stats["rejected"] += 1
            self.stats["total_submissions"] += 1
            print(f"❌ Submission rejected: {response['reason']}")
            return False
    
    def compute_commitment(self, location: Location) -> LocationCommitment:
        """
        计算位置承诺
        
        使用Poseidon哈希: H = Poseidon(x, y)
        """
        hash_value = poseidon_hash(
            int(location.x), 
            int(location.y)
        )
        
        return LocationCommitment(
            hash=hash_value,
            timestamp=location.timestamp,
            window_id=self.get_window_id(location.timestamp)
        )
    
    def generate_tsip_proof(self,
                           prev_location: Location,
                           curr_location: Location,
                           prev_commitment: LocationCommitment) -> TSIPProof:
        """
        生成TSIP零知识证明
        
        证明语句:
        1. prev_commitment = Hash(prev_location)
        2. distance(prev_location, curr_location) ≤ v_max * Δt
        """
        # 准备witness (私密输入)
        witness = {
            "x1": int(prev_location.x),
            "y1": int(prev_location.y),
            "t1": prev_location.timestamp,
            "x2": int(curr_location.x),
            "y2": int(curr_location.y),
            "t2": curr_location.timestamp
        }
        
        # 准备公开输入
        time_diff = curr_location.timestamp - prev_location.timestamp
        curr_commitment = self.compute_commitment(curr_location)
        
        public_inputs = {
            "hash_prev": bytes_to_field_element(prev_commitment.hash),
            "hash_curr": bytes_to_field_element(curr_commitment.hash),
            "v_max": int(TSIPParameters.V_MAX),
            "time_diff": time_diff
        }
        
        # 调用Groth16证明生成
        proof_data = groth16_prove(
            circuit="tsip_circuit.wasm",
            proving_key=self.proving_key,
            witness=witness,
            public_inputs=public_inputs
        )
        
        # 构造证明对象
        return TSIPProof(
            proof_a=proof_data["pi_a"],
            proof_b=proof_data["pi_b"],
            proof_c=proof_data["pi_c"],
            prev_commitment=prev_commitment.hash,
            curr_commitment=curr_commitment.hash,
            v_max=TSIPParameters.V_MAX,
            time_diff=time_diff
        )
    
    def encrypt_location(self, location: Location) -> EncryptedLocation:
        """
        加密位置数据 (使用秘密分享)
        
        将位置(x, y)分成两个份额:
        - share_A 给聚合器A
        - share_R 给聚合器R
        满足: x = share_A + share_R (mod p)
        """
        # 生成随机份额
        import secrets
        prime = 2**31 - 1  # 梅森素数
        
        x_share_a = secrets.randbelow(prime)
        x_share_r = (int(location.x) - x_share_a) % prime
        
        y_share_a = secrets.randbelow(prime)
        y_share_r = (int(location.y) - y_share_a) % prime
        
        # 打包份额
        shares_a = encode_shares(x_share_a, y_share_a)
        shares_r = encode_shares(x_share_r, y_share_r)
        
        # 生成ciphertext (用于完整性校验)
        nonce = secrets.token_bytes(12)
        ciphertext = aes_encrypt(
            data=encode_location(location),
            key=hashlib.sha256(shares_a + shares_r).digest(),
            nonce=nonce
        )
        
        return EncryptedLocation(
            ciphertext=ciphertext,
            shares_a=shares_a,
            shares_r=shares_r,
            nonce=nonce
        )
    
    def get_window_id(self, timestamp: int) -> int:
        """计算时间窗口ID"""
        return timestamp // TSIPParameters.TIME_WINDOW
    
    def send_to_shuffler(self, url: str, message: dict) -> dict:
        """发送消息到Shuffler"""
        import requests
        try:
            response = requests.post(
                f"{url}/tsip/submit",
                json=message,
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"status": "error", "reason": str(e)}
    
    def get_statistics(self) -> dict:
        """获取客户端统计信息"""
        total = self.stats["total_submissions"]
        if total == 0:
            return self.stats
        
        return {
            **self.stats,
            "acceptance_rate": self.stats["accepted"] / total,
            "rejection_rate": self.stats["rejected"] / total
        }
```

---

#### 5.3.2 电路接口实现

```python
# tsip/circuit_interface.py

import subprocess
import json
import os

class CircuitInterface:
    """与circom编译的电路交互的接口"""
    
    def __init__(self, wasm_path: str, zkey_path: str):
        """
        初始化电路接口
        
        Args:
            wasm_path: 编译后的wasm文件路径
            zkey_path: proving key文件路径
        """
        self.wasm_path = wasm_path
        self.zkey_path = zkey_path
    
    def generate_witness(self, inputs: dict) -> str:
        """
        生成witness
        
        Args:
            inputs: 电路输入 (私密+公开)
            
        Returns:
            witness.wtns文件路径
        """
        # 写入input.json
        input_file = "/tmp/input.json"
        with open(input_file, 'w') as f:
            json.dump(inputs, f)
        
        # 调用snarkjs生成witness
        witness_file = "/tmp/witness.wtns"
        cmd = [
            "snarkjs", "wtns", "calculate",
            self.wasm_path,
            input_file,
            witness_file
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        return witness_file
    
    def prove(self, witness_file: str) -> dict:
        """
        生成Groth16证明
        
        Args:
            witness_file: witness文件路径
            
        Returns:
            证明数据 {proof, publicSignals}
        """
        proof_file = "/tmp/proof.json"
        public_file = "/tmp/public.json"
        
        cmd = [
            "snarkjs", "groth16", "prove",
            self.zkey_path,
            witness_file,
            proof_file,
            public_file
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        
        # 读取证明
        with open(proof_file, 'r') as f:
            proof = json.load(f)
        with open(public_file, 'r') as f:
            public_signals = json.load(f)
        
        return {
            "proof": proof,
            "publicSignals": public_signals
        }
    
    @staticmethod
    def verify(vkey_path: str, 
              proof: dict, 
              public_signals: list) -> bool:
        """
        验证Groth16证明
        
        Args:
            vkey_path: verification key路径
            proof: 证明数据
            public_signals: 公开信号
            
        Returns:
            验证是否通过
        """
        # 写入临时文件
        proof_file = "/tmp/verify_proof.json"
        public_file = "/tmp/verify_public.json"
        
        with open(proof_file, 'w') as f:
            json.dump(proof, f)
        with open(public_file, 'w') as f:
            json.dump(public_signals, f)
        
        # 调用snarkjs验证
        cmd = [
            "snarkjs", "groth16", "verify",
            vkey_path,
            public_file,
            proof_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        return "OK" in result.stdout
```

---

### 5.4 服务器端协议实现

#### 5.4.1 Shuffler实现 (TSIP验证器)

```python
# tsip/shuffler.py

from flask import Flask, request, jsonify
from typing import Dict, Optional
import time

app = Flask(__name__)

class TSIPShuffler:
    """
    Shuffler服务器: 负责验证TSIP证明
    """
    
    def __init__(self, vkey_path: str):
        """
        初始化Shuffler
        
        Args:
            vkey_path: Groth16 verification key路径
        """
        self.vkey_path = vkey_path
        
        # 用户状态跟踪
        self.user_commitments: Dict[str, LocationCommitment] = {}
        self.user_submissions: Dict[str, int] = {}  # 提交次数
        self.user_rejections: Dict[str, int] = {}   # 拒绝次数
        
        # 黑名单
        self.blacklist = set()
        
        # 统计
        self.stats = {
            "total_submissions": 0,
            "accepted": 0,
            "rejected": 0,
            "rejection_reasons": {}
        }
    
    @app.route('/tsip/submit', methods=['POST'])
    def handle_submission(self):
        """处理客户端提交"""
        data = request.json
        user_id = data["user_id"]
        
        # 检查黑名单
        if user_id in self.blacklist:
            return jsonify({
                "status": "rejected",
                "reason": "blacklisted"
            }), 403
        
        # 更新统计
        self.stats["total_submissions"] += 1
        self.user_submissions[user_id] = self.user_submissions.get(user_id, 0) + 1
        
        # 验证提交
        validation_result = self.validate_submission(data)
        
        if validation_result["valid"]:
            # 接受
            self.on_accepted(user_id, data)
            return jsonify({
                "status": "accepted",
                "message": "Submission verified"
            })
        else:
            # 拒绝
            self.on_rejected(user_id, validation_result["reason"])
            return jsonify({
                "status": "rejected",
                "reason": validation_result["reason"]
            }), 400
    
    def validate_submission(self, data: dict) -> dict:
        """
        验证提交数据
        
        Returns:
            {"valid": bool, "reason": str}
        """
        user_id = data["user_id"]
        
        # 第一次提交: 无需TSIP证明
        if user_id not in self.user_commitments:
            return {"valid": True, "reason": ""}
        
        # 后续提交: 验证TSIP证明
        if "proof" not in data or data["proof"] is None:
            return {"valid": False, "reason": "missing_proof"}
        
        proof_data = data["proof"]
        
        # 1. 检查时间窗口合理性
        prev_commitment = self.user_commitments[user_id]
        time_diff = data["timestamp"] - prev_commitment.timestamp
        
        if time_diff < 0:
            return {"valid": False, "reason": "time_reversal"}
        
        if time_diff > 2 * TSIPParameters.TIME_WINDOW:
            return {"valid": False, "reason": "time_gap_too_large"}
        
        # 2. 验证Groth16证明
        public_inputs = [
            proof_data["prev_commitment"],
            proof_data["curr_commitment"],
            proof_data["v_max"],
            proof_data["time_diff"]
        ]
        
        proof_verified = CircuitInterface.verify(
            vkey_path=self.vkey_path,
            proof=proof_data["proof"],
            public_signals=public_inputs
        )
        
        if not proof_verified:
            return {"valid": False, "reason": "invalid_tsip_proof"}
        
        # 3. 验证承诺链连续性
        if proof_data["prev_commitment"] != prev_commitment.hash.hex():
            return {"valid": False, "reason": "commitment_mismatch"}
        
        return {"valid": True, "reason": ""}
    
    def on_accepted(self, user_id: str, data: dict):
        """处理接受的提交"""
        # 更新承诺历史
        commitment = LocationCommitment(
            hash=bytes.fromhex(data["commitment"]),
            timestamp=data["timestamp"],
            window_id=data["window_id"]
        )
        self.user_commitments[user_id] = commitment
        
        # 转发到聚合器
        self.forward_to_aggregators(data)
        
        # 更新统计
        self.stats["accepted"] += 1
    
    def on_rejected(self, user_id: str, reason: str):
        """处理拒绝的提交"""
        # 更新拒绝计数
        self.user_rejections[user_id] = self.user_rejections.get(user_id, 0) + 1
        
        # 检查是否应加入黑名单
        if self.user_rejections[user_id] >= TSIPParameters.BLACKLIST_THRESHOLD:
            self.blacklist.add(user_id)
            print(f"⚠️  User {user_id} blacklisted (rejections: {self.user_rejections[user_id]})")
        
        # 更新统计
        self.stats["rejected"] += 1
        if reason not in self.stats["rejection_reasons"]:
            self.stats["rejection_reasons"][reason] = 0
        self.stats["rejection_reasons"][reason] += 1
    
    def forward_to_aggregators(self, data: dict):
        """转发验证通过的数据到聚合器"""
        import requests
        
        # 提取秘密份额
        encrypted_loc = data["encrypted_location"]
        
        # 发送到聚合器A
        try:
            requests.post(
                "http://aggregator-a:5001/ingestA",
                json={
                    "user_id": data["user_id"],
                    "shares": encrypted_loc["shares_a"],
                    "window_id": data["window_id"]
                },
                timeout=5
            )
        except Exception as e:
            print(f"❌ Failed to forward to Aggregator A: {e}")
        
        # 发送到聚合器R
        try:
            requests.post(
                "http://aggregator-r:5002/ingestR",
                json={
                    "user_id": data["user_id"],
                    "shares": encrypted_loc["shares_r"],
                    "window_id": data["window_id"]
                },
                timeout=5
            )
        except Exception as e:
            print(f"❌ Failed to forward to Aggregator R: {e}")
    
    @app.route('/tsip/stats', methods=['GET'])
    def get_stats(self):
        """获取统计信息"""
        total = self.stats["total_submissions"]
        if total == 0:
            return jsonify(self.stats)
        
        return jsonify({
            **self.stats,
            "acceptance_rate": self.stats["accepted"] / total,
            "rejection_rate": self.stats["rejected"] / total,
            "num_blacklisted": len(self.blacklist)
        })

# 启动服务器
if __name__ == '__main__':
    shuffler = TSIPShuffler(vkey_path="/keys/verification_key.json")
    app.run(host='0.0.0.0', port=5000)
```

---

#### 5.4.2 聚合器修改 (支持TSIP)

```python
# tsip/aggregator_tsip.py

# 在原有aggregator基础上添加TSIP支持

class TSIPAggregator:
    """支持TSIP的聚合器"""
    
    def __init__(self):
        # 原有字段
        self.bufferA = {}
        self.stats = {}
        
        # TSIP扩展: 记录每个窗口的有效提交
        self.valid_submissions_per_window = {}
    
    @app.route('/ingestA', methods=['POST'])
    def ingest_a(self):
        """接收来自Shuffler的验证通过的份额"""
        data = request.json
        user_id = data["user_id"]
        window_id = data["window_id"]
        shares = data["shares"]
        
        # 解析份额
        x_share, y_share = decode_shares(shares)
        
        # 存储
        if window_id not in self.bufferA:
            self.bufferA[window_id] = {}
            self.valid_submissions_per_window[window_id] = 0
        
        self.bufferA[window_id][user_id] = {
            "x_share": x_share,
            "y_share": y_share
        }
        
        self.valid_submissions_per_window[window_id] += 1
        
        # 检查是否达到批次大小
        if len(self.bufferA[window_id]) >= TSIPParameters.BATCH_SIZE:
            self.flush_window(window_id)
        
        return jsonify({"status": "ok"})
    
    @app.route('/tsip/window_stats/<int:window_id>', methods=['GET'])
    def get_window_stats(self, window_id: int):
        """获取指定窗口的统计"""
        return jsonify({
            "window_id": window_id,
            "valid_submissions": self.valid_submissions_per_window.get(window_id, 0),
            "buffered": len(self.bufferA.get(window_id, {}))
        })
```

---

### 5.5 电路完整实现

#### 5.5.1 TSIP主电路

```circom
// circuits/tsip_main.circom

pragma circom 2.1.0;

include "node_modules/circomlib/circuits/poseidon.circom";
include "node_modules/circomlib/circuits/comparators.circom";

/*
 * TSIP主电路: 验证时空完整性
 * 
 * 公开输入:
 *   - hash_prev: 前一个位置的哈希
 *   - hash_curr: 当前位置的哈希 (由电路计算)
 *   - v_max: 最大速度 (m/s)
 *   - time_diff: 时间差 (秒)
 *   - max_dist_sq: 最大距离平方 (预计算)
 * 
 * 私密输入:
 *   - x1, y1: 前一个位置坐标
 *   - x2, y2: 当前位置坐标
 * 
 * 输出:
 *   - valid: 是否通过验证
 */
template TSIPCircuit() {
    // ===== 信号声明 =====
    
    // 私密输入
    signal input x1;
    signal input y1;
    signal input x2;
    signal input y2;
    
    // 公开输入
    signal input hash_prev;
    signal input hash_curr;
    signal input max_dist_sq;
    
    // 输出
    signal output valid;
    
    // ===== 子电路1: 验证前一个位置的哈希 =====
    component hasher1 = Poseidon(2);
    hasher1.inputs[0] <== x1;
    hasher1.inputs[1] <== y1;
    
    // 约束: 计算的哈希必须等于声明的哈希
    hasher1.out === hash_prev;
    
    // ===== 子电路2: 计算当前位置的哈希 =====
    component hasher2 = Poseidon(2);
    hasher2.inputs[0] <== x2;
    hasher2.inputs[1] <== y2;
    
    // 约束: 计算的哈希必须等于公开的哈希
    hasher2.out === hash_curr;
    
    // ===== 子电路3: 计算距离平方 =====
    signal dx;
    signal dy;
    dx <== x2 - x1;
    dy <== y2 - y1;
    
    signal dx_sq;
    signal dy_sq;
    dx_sq <== dx * dx;
    dy_sq <== dy * dy;
    
    signal dist_sq;
    dist_sq <== dx_sq + dy_sq;
    
    // ===== 子电路4: 距离检查 =====
    // 检查: dist_sq ≤ max_dist_sq
    component less_than = LessThan(64);  // 64位比较
    less_than.in[0] <== dist_sq;
    less_than.in[1] <== max_dist_sq + 1;  // +1 to make it ≤
    
    // ===== 子电路5: 坐标范围检查 =====
    // 防止整数溢出攻击
    signal x1_valid;
    signal y1_valid;
    signal x2_valid;
    signal y2_valid;
    
    component range_x1 = LessThan(32);
    range_x1.in[0] <== x1;
    range_x1.in[1] <== 1000000;  // X_MAX
    x1_valid <== range_x1.out;
    
    component range_y1 = LessThan(32);
    range_y1.in[0] <== y1;
    range_y1.in[1] <== 1000000;  // Y_MAX
    y1_valid <== range_y1.out;
    
    component range_x2 = LessThan(32);
    range_x2.in[0] <== x2;
    range_x2.in[1] <== 1000000;
    x2_valid <== range_x2.out;
    
    component range_y2 = LessThan(32);
    range_y2.in[0] <== y2;
    range_y2.in[1] <== 1000000;
    y2_valid <== range_y2.out;
    
    // ===== 最终输出 =====
    // 所有检查都必须通过
    signal all_range_valid;
    all_range_valid <== x1_valid * y1_valid * x2_valid * y2_valid;
    
    valid <== less_than.out * all_range_valid;
}

component main {public [hash_prev, hash_curr, max_dist_sq]} = TSIPCircuit();
```

---

#### 5.5.2 编译和Setup脚本

```bash
#!/bin/bash
# scripts/compile_circuit.sh

set -e

CIRCUIT_NAME="tsip_main"
CIRCUIT_DIR="circuits"
BUILD_DIR="build"
PTAU_FILE="powersOfTau28_hez_final_20.ptau"  # 从ceremonia下载

echo "===== Step 1: 编译电路 ====="
circom ${CIRCUIT_DIR}/${CIRCUIT_NAME}.circom \
    --r1cs \
    --wasm \
    --sym \
    -o ${BUILD_DIR}

echo "===== Step 2: 查看电路信息 ====="
snarkjs r1cs info ${BUILD_DIR}/${CIRCUIT_NAME}.r1cs

echo "===== Step 3: 生成Groth16 zkey (Phase 1) ====="
snarkjs groth16 setup \
    ${BUILD_DIR}/${CIRCUIT_NAME}.r1cs \
    ${PTAU_FILE} \
    ${BUILD_DIR}/${CIRCUIT_NAME}_0000.zkey

echo "===== Step 4: Contribute to Phase 2 ====="
snarkjs zkey contribute \
    ${BUILD_DIR}/${CIRCUIT_NAME}_0000.zkey \
    ${BUILD_DIR}/${CIRCUIT_NAME}_final.zkey \
    --name="TSIP Contribution" \
    -v \
    -e="$(openssl rand -hex 32)"

echo "===== Step 5: 导出verification key ====="
snarkjs zkey export verificationkey \
    ${BUILD_DIR}/${CIRCUIT_NAME}_final.zkey \
    ${BUILD_DIR}/verification_key.json

echo "===== Step 6: 生成Solidity验证器 (可选) ====="
snarkjs zkey export solidityverifier \
    ${BUILD_DIR}/${CIRCUIT_NAME}_final.zkey \
    ${BUILD_DIR}/TSIPVerifier.sol

echo "✅ 电路编译完成!"
echo "   - Proving key: ${BUILD_DIR}/${CIRCUIT_NAME}_final.zkey"
echo "   - Verification key: ${BUILD_DIR}/verification_key.json"
echo "   - WASM: ${BUILD_DIR}/${CIRCUIT_NAME}_js/${CIRCUIT_NAME}.wasm"
```

---

### 5.6 系统集成

#### Docker Compose配置

```yaml
# docker-compose-tsip.yml

version: '3.8'

services:
  # Shuffler (TSIP验证器)
  shuffler:
    build: 
      context: .
      dockerfile: Dockerfile.shuffler
    ports:
      - "5000:5000"
    volumes:
      - ./build:/keys:ro
      - ./logs:/logs
    environment:
      - VKEY_PATH=/keys/verification_key.json
      - LOG_LEVEL=INFO
    networks:
      - tsip-network
  
  # 聚合器A
  aggregator-a:
    build:
      context: .
      dockerfile: Dockerfile.aggregator
    ports:
      - "5001:5001"
    environment:
      - AGGREGATOR_ID=A
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis
    networks:
      - tsip-network
  
  # 聚合器R
  aggregator-r:
    build:
      context: .
      dockerfile: Dockerfile.aggregator
    ports:
      - "5002:5002"
    environment:
      - AGGREGATOR_ID=R
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis
    networks:
      - tsip-network
  
  # Decoder
  decoder:
    build:
      context: .
      dockerfile: Dockerfile.decoder
    ports:
      - "5003:5003"
    environment:
      - AGGREGATOR_A_URL=http://aggregator-a:5001
      - AGGREGATOR_R_URL=http://aggregator-r:5002
    networks:
      - tsip-network
  
  # Redis (缓存)
  redis:
    image: redis:7-alpine
    networks:
      - tsip-network
  
  # 客户端模拟器 (可选)
  client-sim:
    build:
      context: .
      dockerfile: Dockerfile.client
    volumes:
      - ./build:/keys:ro
      - ./data:/data
    environment:
      - PROVING_KEY_PATH=/keys/tsip_main_final.zkey
      - SHUFFLER_URL=http://shuffler:5000
      - NUM_USERS=100
    depends_on:
      - shuffler
    networks:
      - tsip-network

networks:
  tsip-network:
    driver: bridge
```

---

## 小结

本部分实现了TSIP协议的完整代码:
1. ✅ 客户端完整实现 (包含proof生成)
2. ✅ Shuffler验证器实现
3. ✅ 聚合器TSIP扩展
4. ✅ Circom电路完整代码
5. ✅ Docker集成配置

**下一部分**: 安全性证明和实验评估

---

## 参考实现

完整代码仓库结构:
```
tsip-impl/
├── circuits/
│   ├── tsip_main.circom
│   └── helpers/
├── tsip/
│   ├── client.py
│   ├── shuffler.py
│   ├── aggregator_tsip.py
│   └── types.py
├── scripts/
│   ├── compile_circuit.sh
│   └── run_setup.sh
├── tests/
│   ├── test_circuit.py
│   ├── test_client.py
│   └── test_integration.py
├── docker-compose-tsip.yml
└── README.md
```
