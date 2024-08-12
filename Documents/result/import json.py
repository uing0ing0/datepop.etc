import json
import requests
import time
from PIL import Image
import os
import numpy as np

def split_image(image_path, max_size=2000):
    with Image.open(image_path) as img:
        # Resize the image if it's too large
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.LANCZOS)
            print(f"Image resized to {img.size}")
        
        width, height = img.size
        mid_x = width // 2
        
        left_half = img.crop((0, 0, mid_x, height))
        right_half = img.crop((mid_x, 0, width, height))
        
        left_path = "left_half.jpg"
        right_path = "right_half.jpg"
        left_half.save(left_path)
        right_half.save(right_path)
        
        return [left_path, right_path], mid_x

def combine_images(images, blend_width=50):
    left_img, right_img = images
    print(f"Left image size: {left_img.size}")
    print(f"Right image size: {right_img.size}")
    
    # Convert images to numpy arrays
    left_array = np.array(left_img)
    right_array = np.array(right_img)
    
    # Calculate dimensions
    height = max(left_array.shape[0], right_array.shape[0])
    total_width = left_array.shape[1] + right_array.shape[1] - blend_width
    
    # Create the output array
    result = np.zeros((height, total_width, 3), dtype=np.uint8)
    
    # Copy the left image
    result[:left_array.shape[0], :left_array.shape[1]] = left_array
    
    # Create a weight array for blending
    blend_region = np.linspace(0, 1, blend_width)
    blend_region = blend_region.reshape(1, blend_width, 1)
    
    # Blend the overlapping region
    overlap_left = left_array[:, -blend_width:]
    overlap_right = right_array[:, :blend_width]
    blended = overlap_left * (1 - blend_region) + overlap_right * blend_region
    
    # Copy the blended region and the rest of the right image
    result[:blended.shape[0], left_array.shape[1]-blend_width:left_array.shape[1]] = blended
    result[:right_array.shape[0], left_array.shape[1]:] = right_array[:, blend_width:]
    
    # Convert back to PIL Image
    combined = Image.fromarray(result)
    return combined

def leonardo_ai_upscale(api_key, image_file_path):
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Bearer {api_key}"
    }

    print(f"Starting upscale for {image_file_path}")

    # 1. 이미지 업로드를 위한 사전 서명된 URL 얻기
    url = "https://cloud.leonardo.ai/api/rest/v1/init-image"
    payload = {"extension": "jpg"}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error in getting presigned URL: {e}")
        return None

    # 2. 사전 서명된 URL을 통해 이미지 업로드
    response_data = response.json()
    fields = json.loads(response_data['uploadInitImage']['fields'])
    url = response_data['uploadInitImage']['url']
    image_id = response_data['uploadInitImage']['id']

    print("Uploading image...")
    files = {'file': ('image.jpg', open(image_file_path, 'rb'), 'image/jpeg')}
    try:
        response = requests.post(url, data=fields, files=files, timeout=60)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error in uploading image: {e}")
        return None

    # 3. Universal Upscaler를 사용하여 업스케일 생성
    url = "https://cloud.leonardo.ai/api/rest/v1/variations/universal-upscaler"
    payload = {
        "upscalerStyle": "General",
        "creativityStrength": 6,
        "upscaleMultiplier": 1.5,
        "initImageId": image_id
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error in Universal Upscaler: {e}")
        return None

    variation_id = response.json()['universalUpscaler']['id']

    # 4. 변형 ID를 통해 업스케일된 이미지 가져오기
    url = f"https://cloud.leonardo.ai/api/rest/v1/variations/{variation_id}"
    max_attempts = 20
    for attempt in range(max_attempts):
        print(f"Checking upscale status... Attempt {attempt + 1}/{max_attempts}")
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            result = response.json()
            
            if 'generated_image_variation_generic' in result and result['generated_image_variation_generic']:
                if result['generated_image_variation_generic'][0].get('status') == 'COMPLETE':
                    upscaled_image_url = result['generated_image_variation_generic'][0]['url']
                    print("Upscale completed. Downloading image...")
                    image_response = requests.get(upscaled_image_url, timeout=30)
                    if image_response.status_code == 200:
                        upscaled_file_name = f"upscaled_tile_{int(time.time())}.jpg"
                        with open(upscaled_file_name, "wb") as f:
                            f.write(image_response.content)
                        print(f"Upscaled image saved as {upscaled_file_name}.")
                        return upscaled_file_name
                    else:
                        print("Failed to download the upscaled image")
                        return None
            time.sleep(15)  # 15초 대기
        except requests.exceptions.RequestException as e:
            print(f"Error in checking upscale status: {e}")
            time.sleep(15)  # 오류 발생 시에도 대기

    print("Max attempts reached. Upscaling may have failed.")
    return None

def leonardo_ai_upscale_tiled(api_key, image_file_path):
    with Image.open(image_file_path) as img:
        width, height = img.size
        total_pixels = width * height
        
    if total_pixels <= 20000000:  # 20MP 이하인 경우
        print("Image is 20MP or smaller. Upscaling without splitting.")
        result = leonardo_ai_upscale(api_key, image_file_path)
        if result is not None:
            os.rename(result, "/Users/eunyoungkim/Documents/result/final_upscaled_image.jpg")
            print("Final upscaled image saved as 'final_upscaled_image.jpg'")
            return "final_upscaled_image.jpg"
        else:
            print("Failed to upscale the image")
            return None
    else:
        print("Image is larger than 20MP. Splitting and upscaling.")
        # 기존의 분할 및 업스케일 로직
        print("Starting image split")
        tile_paths, mid_x = split_image(image_file_path)
        print(f"Image split completed. Mid point: {mid_x}")
        
        upscaled_tile_paths = []
        for i, tile_path in enumerate(tile_paths):
            print(f"Upscaling tile {i+1}")
            result = leonardo_ai_upscale(api_key, tile_path)
            if result is not None:
                upscaled_tile_paths.append(result)
                print(f"Tile {i+1} upscaled successfully")
            else:
                print(f"Failed to upscale tile: {tile_path}")
                return None
        
        print("All tiles upscaled, combining images")
        upscaled_tiles = [Image.open(path) for path in upscaled_tile_paths]
        
        merged_image = combine_images(upscaled_tiles)
        merged_image.save("/Users/eunyoungkim/Documents/result/final_upscaled_image.jpg")
        print("Final upscaled image saved as 'final_upscaled_image.jpg'")
        
        print("Cleaning up temporary files")
        for path in tile_paths + upscaled_tile_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
                    print(f"Removed temporary file: {path}")
                else:
                    print(f"File not found: {path}")
            except Exception as e:
                print(f"Error removing file {path}: {e}")
        
        return "final_upscaled_image.jpg"
    


    
api_key = "2c2accfc-3306-439f-bb6f-509bab3129c3"
image_file_path = "/Users/eunyoungkim/Documents/result/tile_2.jpg"
result = leonardo_ai_upscale_tiled(api_key, image_file_path)

if result is not None:
    print(f"Successfully upscaled and merged image: {result}")
else:
    print("Failed to upscale the image using tiling method.")