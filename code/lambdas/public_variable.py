import boto3
import json
from typing import Dict, Any, Optional
import time

class OutputFormatManager:
    """管理共享的 output_format 配置"""
    
    def __init__(self, parameter_prefix: str = "/lambda-shared/output-format"):
        self.parameter_prefix = parameter_prefix
        self.ssm = boto3.client('ssm')
        
        # 內存緩存配置
        self._cache = {}
        self._cache_expiry = {}
        self._cache_ttl = 300  # 5分鐘緩存
    
    def set_output_format(self, format_data: Dict[str, Any], version: str = "latest") -> bool:
        """設置 output_format 配置"""
        try:
            parameter_name = f"{self.parameter_prefix}/{version}"
            
            # 將字典轉換為JSON字符串
            json_data = json.dumps(format_data, ensure_ascii=False, indent=2)
            
            # 檢查大小限制（Parameter Store限制4KB）
            if len(json_data.encode('utf-8')) > 4096:
                raise ValueError(f"配置數據過大: {len(json_data.encode('utf-8'))} bytes (最大4096)")
            
            # 存儲到Parameter Store
            self.ssm.put_parameter(
                Name=parameter_name,
                Value=json_data,
                Type='String',
                Overwrite=True,
                Description=f"Output format configuration - version {version}"
            )
            
            # 清除相關緩存
            self._clear_cache(version)
            
            print(f"✅ Output format (version {version}) saved successfully")
            return True
            
        except Exception as e:
            print(f"❌ Error saving output format: {e}")
            return False
    
    def get_output_format(self, version: str = "latest", use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """獲取 output_format 配置"""
        
        # 檢查緩存
        if use_cache and self._is_cached_valid(version):
            print(f"📋 Using cached output format (version {version})")
            return self._cache[version]
        
        try:
            parameter_name = f"{self.parameter_prefix}/{version}"
            
            response = self.ssm.get_parameter(Name=parameter_name)
            json_data = response['Parameter']['Value']
            
            # 解析JSON
            format_data = json.loads(json_data)
            
            # 更新緩存
            if use_cache:
                self._cache[version] = format_data
                self._cache_expiry[version] = time.time() + self._cache_ttl
            
            print(f"✅ Output format (version {version}) loaded successfully")
            return format_data
            
        except self.ssm.exceptions.ParameterNotFound:
            print(f"❌ Output format version '{version}' not found")
            return None
        except json.JSONDecodeError as e:
            print(f"❌ Error parsing output format JSON: {e}")
            return None
        except Exception as e:
            print(f"❌ Error loading output format: {e}")
            return None
    
    def list_versions(self) -> list:
        """列出所有可用的版本"""
        try:
            response = self.ssm.get_parameters_by_path(
                Path=self.parameter_prefix,
                Recursive=True
            )
            
            versions = []
            for param in response['Parameters']:
                version = param['Name'].split('/')[-1]
                versions.append({
                    'version': version,
                    'last_modified': param['LastModifiedDate'].isoformat(),
                    'description': param.get('Description', '')
                })
            
            return sorted(versions, key=lambda x: x['last_modified'], reverse=True)
            
        except Exception as e:
            print(f"❌ Error listing versions: {e}")
            return []
    
    def delete_version(self, version: str) -> bool:
        """刪除指定版本"""
        try:
            parameter_name = f"{self.parameter_prefix}/{version}"
            self.ssm.delete_parameter(Name=parameter_name)
            
            # 清除緩存
            self._clear_cache(version)
            
            print(f"✅ Output format version '{version}' deleted")
            return True
            
        except Exception as e:
            print(f"❌ Error deleting version '{version}': {e}")
            return False
    
    def _is_cached_valid(self, version: str) -> bool:
        """檢查緩存是否有效"""
        if version not in self._cache:
            return False
        
        if version not in self._cache_expiry:
            return False
        
        return time.time() < self._cache_expiry[version]
    
    def _clear_cache(self, version: str = None):
        """清除緩存"""
        if version:
            self._cache.pop(version, None)
            self._cache_expiry.pop(version, None)
        else:
            self._cache.clear()
            self._cache_expiry.clear()
    
    def get_topics_list(self, version: str = "latest") -> list:
        """獲取所有主題列表"""
        format_data = self.get_output_format(version)
        if format_data:
            return list(format_data.keys())
        return []
    
    def get_topic_config(self, topic: str, version: str = "latest") -> Optional[Dict[str, Any]]:
        """獲取特定主題的配置"""
        format_data = self.get_output_format(version)
        if format_data and topic in format_data:
            return format_data[topic]
        return None
    
    def get_subtopics(self, topic: str, version: str = "latest") -> list:
        """獲取特定主題的子主題列表"""
        topic_config = self.get_topic_config(topic, version)
        if topic_config and 'subtopics' in topic_config:
            return [subtopic['title'] for subtopic in topic_config['subtopics']]
        return []


# 全局實例 - 可以在所有Lambda中使用
output_format_manager = OutputFormatManager()

# 便利函數
def get_output_format(version: str = "latest") -> Optional[Dict[str, Any]]:
    """便利函數：獲取output_format"""
    return output_format_manager.get_output_format(version)

def get_topic_config(topic: str, version: str = "latest") -> Optional[Dict[str, Any]]:
    """便利函數：獲取主題配置"""
    return output_format_manager.get_topic_config(topic, version)


# ============================================================================
# 初始化腳本 - 用於第一次設置
# ============================================================================

def initialize_output_format():
    """初始化 output_format 到 Parameter Store"""
    
    output_format = {
      "市場概況與趨勢": {
        "title": "市場概況與趨勢",
        "subtopics": [
          {
            "title": "產業規模與成長",
            "subsubtopics": [
              "台灣市場規模與成長",
              "產品類型演進",
              "年度銷售變化",
              "驅動因素與未來展望"
            ]
          },
          {
            "title": "主導品牌分析",
            "subsubtopics": [
              "主導品牌銷售概況",
              "價格帶分析",
              "平價帶市場概況",
              "高價帶市場概況",
              "價格帶結構與策略定位",
              "價格帶市佔變化趨勢"
            ]
          },
          # {
          #   "title": "消費者痛點與聲量",
          #   "subsubtopics": [
          #     "痛點分析",
          #     "正面熱點事件",
          #     "負面熱點事件",
          #     "聲量與情緒趨勢",
          #     "痛點轉化機會"
          #   ]
          # },
          # {
          #   "title": "未來政策與永續趨勢",
          #   "subsubtopics": [
          #     "國際政策動向",
          #     "台灣政策動向",
          #     "ESG 與永續議題"
          #   ]
          # },
          # {
          #   "title": "市場概況與趨勢總結",
          #   "subsubtopics": [
          #       "市場概況總結",
          #       "Why 為何是這些變化重要",
          #       "How 品牌該如何應對市場變化"
          #   ]
          # }
        ]
      },
      "品牌定位與形象": {
        "title": "品牌定位與形象",
        "subtopics": [
          {
            "title": "品牌價格與功能定位",
            "subsubtopics": []
          },
          {
            "title": "品牌形象",
            "subsubtopics": []
          },
          {
            "title": "獨特銷售主張（USP）",
            "subsubtopics": []
          }
        ]
      },
      "產品分析": {
        "title": "產品分析",
        "subtopics": [
          {
            "title": "熱銷產品銷量",
            "subsubtopics": []
          },
          {
            "title": "主打銷售通路",
            "subsubtopics": []
          },
          {
            "title": "目標族群與使用情境",
            "subsubtopics": []
          },
          {
            "title": "產品獨特銷售主張",
            "subsubtopics": []
          }
        ]
      },
      "消費者行為與洞察": {
        "title": "消費者行為與洞察",
        "subtopics": [
          {
            "title": "顧客輪廓",
            "subsubtopics": [
              "人口屬性",
              "生活型態",
              "消費力與行為"
            ]
          },
          {
            "title": "購買動機",
            "subsubtopics": []
          },
          {
            "title": "廣告投放策略",
            "subsubtopics": [
              "線上投放策略",
              "線下場域策略"
            ]
          },
          {
            "title": "Persona",
            "subsubtopics": []
          }
        ]
      },
      "競品分析": {
        "title": "競品分析",
        "subtopics": [
          {
            "title": "功能對比",
            "subsubtopics": []
          },
          {
            "title": "通路對比",
            "subsubtopics": []
          },
          {
            "title": "受眾與使用情境差異",
            "subsubtopics": []
          },
          {
            "title": "競品獨特銷售主張",
            "subsubtopics": []
          },
          {
            "title": "產品優劣點",
            "subsubtopics": []
          }
        ]
      },
      "結論與建議": {
        "title": "結論與建議",
        "subtopics": [
          {
            "title": "產品賣點",
            "subsubtopics": []
          },
          {
            "title": "行銷策略",
            "subsubtopics": []
          }
        ]
      }
    }
    
    manager = OutputFormatManager()
    
    # 設置最新版本
    success = manager.set_output_format(output_format, "latest")
    
    if success:
        # 也可以設置帶時間戳的版本用於備份
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        manager.set_output_format(output_format, f"v_{timestamp}")
        
        print("🎉 Output format initialized successfully!")
        print("📋 Available topics:")
        for topic in output_format.keys():
            print(f"  - {topic}")
    
    return success


# ============================================================================
# 使用範例
# ============================================================================

def example_lambda_invoke_usage():
    """invoke-lambda 中的使用範例"""
    
    # 獲取完整的 output_format
    output_format = get_output_format()
    if not output_format:
        return {"error": "Unable to load output format"}
    
    # 獲取特定主題的配置
    topic = "市場概況與趨勢"
    topic_config = get_topic_config(topic)
    
    if topic_config:
        print(f"📊 處理主題: {topic_config['title']}")
        print(f"📝 子主題數量: {len(topic_config['subtopics'])}")
        
        # 構建輸出結果
        result = build_output_format(raw_analysis, topic, txt2figure_results)
        return result
    
    return {"error": f"Topic '{topic}' not found"}

def example_lambda_export_usage():
    """export-lambda 中的使用範例"""
    
    # 獲取 output_format 用於生成文檔結構
    output_format = get_output_format()
    if not output_format:
        return {"error": "Unable to load output format"}
    
    # 根據 output_format 生成文檔
    for topic_name, topic_config in output_format.items():
        print(f"📄 生成章節: {topic_config['title']}")
        
        for subtopic in topic_config.get('subtopics', []):
            print(f"  📋 子章節: {subtopic['title']}")
            
            if subtopic.get('subsubtopics'):
                for subsubtopic in subtopic['subsubtopics']:
                    print(f"    📝 小節: {subsubtopic}")
    
    return {"message": "Document structure processed"}

def example_admin_usage():
    """管理員使用範例"""
    
    manager = OutputFormatManager()
    
    # 列出所有版本
    versions = manager.list_versions()
    print("📋 Available versions:")
    for version in versions:
        print(f"  - {version['version']} (modified: {version['last_modified']})")
    
    # 獲取特定版本
    old_format = manager.get_output_format("v_20241201_120000")
    if old_format:
        print(f"📚 Old format has {len(old_format)} topics")
    
    # 更新配置（新增主題）
    current_format = manager.get_output_format("latest")
    if current_format:
        # 添加新主題
        current_format["新增主題"] = {
            "title": "新增主題",
            "subtopics": []
        }
        
        # 保存新版本
        manager.set_output_format(current_format, "latest")
        print("✅ Configuration updated")


# ============================================================================
# 如果作為腳本執行，則初始化配置
# ============================================================================

if __name__ == "__main__":
    print("🚀 Initializing output format configuration...")
    initialize_output_format()