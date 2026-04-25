import re

with open('backend/app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace variables
content = content.replace('compressed_b64   = None', 'macs_data = None')
content = content.replace('residual_b64     = None', 'residual_data = None')

# Remove b64encode lines
content = re.sub(r'\s*compressed_b64\s*=\s*base64\.b64encode\(macs_data\)\.decode\(\)', '', content)
content = re.sub(r'\s*residual_b64\s*=\s*base64\.b64encode\(residual_data\)\.decode\(\)', '', content)
content = content.replace('residual_b64     = None', 'residual_data   = None')
content = content.replace('residual_b64   = None', 'residual_data   = None')

# Replace the response building
old_response_code = """        response = {
            "status":                        "success",
            "original_filename":             filename,
            "original_size_bytes":           original_size,
            "compressed_size_bytes":         compressed_bytes,
            "residual_size_bytes":           residual_bytes,
            "total_size_bytes":              compressed_bytes + residual_bytes,
            "compression_ratio":             lossy_ratio,
            "total_ratio_with_residual":     total_ratio,
            "space_savings_percent":         lossy_saving,
            "total_savings_with_residual_percent": total_saving,
            "file_type":                     file_type,
            "has_residual":                  has_residual,
            "sha256_original":               sha256_orig_hex,
            "compressed_file_b64":           compressed_b64,
            "residual_file_b64":             residual_b64,
            **extra_metrics,
        }

        return jsonify(response)"""

new_response_code = """        metadata = {
            "status":                        "success",
            "original_filename":             filename,
            "original_size_bytes":           original_size,
            "compressed_size_bytes":         compressed_bytes,
            "residual_size_bytes":           residual_bytes,
            "total_size_bytes":              compressed_bytes + residual_bytes,
            "compression_ratio":             lossy_ratio,
            "total_ratio_with_residual":     total_ratio,
            "space_savings_percent":         lossy_saving,
            "total_savings_with_residual_percent": total_saving,
            "file_type":                     file_type,
            "has_residual":                  has_residual,
            "sha256_original":               sha256_orig_hex,
            **extra_metrics,
        }

        import json
        from flask import Response, stream_with_context

        def generate_json_stream():
            yield '{"compressed_file_b64":"'
            
            chunk_sz = 3 * 1024 * 1024
            for i in range(0, len(macs_data), chunk_sz):
                yield base64.b64encode(macs_data[i:i+chunk_sz]).decode('ascii')
                
            yield '","residual_file_b64":'
            if residual_data:
                yield '"'
                for i in range(0, len(residual_data), chunk_sz):
                    yield base64.b64encode(residual_data[i:i+chunk_sz]).decode('ascii')
                yield '"'
            else:
                yield 'null'
                
            for k, v in metadata.items():
                yield f',"{k}":{json.dumps(v)}'
                
            yield '}'

        return Response(stream_with_context(generate_json_stream()), mimetype='application/json')"""

content = content.replace(old_response_code, new_response_code)

with open('backend/app.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("done")
