from flask import Flask, request, jsonify

app = Flask(__name__)

REGISTERED_DEVICES = {}

@app.route("/register_device", methods=["POST"])
def register_device():
    data = request.json
    mac_address = data.get("mac_address")
    ip_address = data.get("ip_address")
    if mac_address and ip_address:
        REGISTERED_DEVICES[mac_address] = ip_address
        return jsonify({"message": "Устройство зарегистрировано."}), 200
    return jsonify({"message": "Некорректные данные."}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
