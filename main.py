import base64
import requests
import json
import time
import rsa
from loguru import logger


def encrypt(data: str, public_key_pem: str) -> str:
    public_key = rsa.PublicKey.load_pkcs1_openssl_pem(public_key_pem.encode())
    encrypted = rsa.encrypt(data.encode(), public_key)
    return base64.b64encode(encrypted).decode()


class BaoMiGuan:
    def __init__(self, username, password, courseId, *args, **kwargs):
        self.token = None
        self.log = logger
        self.username = username
        self.password = password
        self.courseId = courseId
        self.session = requests.session()
        self.session.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
            "Content-Type": "application/json",
        }

    def login(self):
        key_url = 'https://www.baomi.org.cn/portal/main-api/getPublishKey.do'
        response = self.session.get(key_url)
        public_key = response.json()['data']
        public_key = f"""
                -----BEGIN PUBLIC KEY-----
                {public_key}
                -----END PUBLIC KEY-----
            """
        login_url = "https://www.baomi.org.cn/portal/main-api/loginInNew.do"
        payload = {
            "loginName": encrypt(self.username, public_key),
            "passWord": encrypt(self.password, public_key),
            "deviceId": 1711,
            "deviceOs": "pc",
            "lon": 40,
            "lat": 30,
            "siteId": "95",
            "sinopec": 'false'
        }
        response = self.session.post(login_url, json=payload).json()
        token = response['token']
        if token == '':
            raise Exception(response['error']['errorMsg'])
        self.token = token
        self.session.headers.update({
            "token": token
        })

    def get_directory_ids(self):
        timestamp = int(time.time())
        url = 'http://www.baomi.org.cn/portal/api/v2/coursePacket/getCourseDirectoryList'
        data = {'scale': 1, 'coursePacketId': self.courseId, 'timestamps': timestamp}
        res = self.session.get(url, params=data).json()
        return res['data']

    def save_course_package(self, resource_id, resource_directory_id, resource_length, study_length, study_time,
                            display_order):
        url = 'http://www.baomi.org.cn/portal/api/v2/studyTime/saveCoursePackage.do'
        timestamp = int(time.time())
        post_data = {
            'courseId': self.courseId,
            'resourceId': resource_id,
            'resourceDirectoryId': resource_directory_id,
            'resourceLength': resource_length,
            'studyLength': study_length,
            'studyTime': study_time,
            'startTime': timestamp - int(resource_length),
            'resourceType': 1,
            'resourceLibId': 3,
            'token': self.token,
            'studyResourceId': display_order,
            'timestamps': timestamp
        }
        try:
            response = self.session.get(url, params=post_data)
            response.raise_for_status()  # 检查响应状态码
            message = response.json()['message']
            self.log.info(message)
        except requests.exceptions.RequestException as e:
            self.log.error(f"保存课程包失败: {e}")

    def view_resource_details(self, resource_directory_id):
        timestamp = int(time.time())
        url = 'http://www.baomi.org.cn/portal/api/v2/coursePacket/viewResourceDetails'
        post_data = {
            'token': self.token,
            'resourceDirectoryId': resource_directory_id,
            'timestamps': timestamp
        }
        try:
            response = self.session.get(url, params=post_data)
            response.raise_for_status()  # 检查响应状态码
            data = response.json()['data']
            resource_length = data['resourceLength']
            resource_id = data['resourceID']
            display_order = data['displayOrder']
            self.log.info(f"正在刷: {data['name']}")
            return resource_length, resource_id, display_order
        except requests.exceptions.RequestException as e:
            self.log.error(f"获取课程时长失败: {e}")
            return None, None, None

    def process_video(self, directory_id):
        timestamp = int(time.time())
        try:
            resource_directory_ids = \
                self.session.get('http://www.baomi.org.cn/portal/api/v2/coursePacket/getCourseResourceList',
                                 params={'coursePacketId': self.courseId, 'directoryId': directory_id,
                                         'timestamps': timestamp}, ).json()['data'][
                    'listdata']
            for resource_info in resource_directory_ids:
                resource_directory_id = resource_info['SYS_UUID']
                directory_id = resource_info['directoryID']
                resource_length, resource_id, display_order = self.view_resource_details(resource_directory_id)
                if resource_length is not None:
                    self.save_course_package(resource_id, resource_directory_id, resource_length, 0,
                                             180,
                                             display_order)
                    self.save_course_package(resource_id, resource_directory_id, resource_length,
                                             resource_length, resource_length, display_order)
                    self.save_course_package(resource_id, resource_directory_id, resource_length,
                                             resource_length, resource_length, display_order)

        except requests.exceptions.RequestException as e:
            self.log.error(f"处理视频失败: {e}")

    def save_exam_result(self):
        questions = self.session.get(
            'https://www.baomi.org.cn/portal/main-api/v2/activity/exam/getExamContentData.do?examId=8ad5a4cf95a7e09701961d54fa6f00d8&randomId=d3c73f8731c1159e5208b3b9c61a8370').json()
        examResult = []
        for i in questions['data']['typeList']:
            for q in i['questionList']:
                examResult.append({
                    "parentId": "0",
                    "qstId": q['id'],
                    "resultFlag": 0,
                    "standardAnswer": q['answer'],
                    "subCount": 0,
                    "tqId": q['tqId'],
                    "userAnswer": q['answer'],
                    "userScoreRate": "100%",
                    "viewTypeId": 1
                })

        url = "https://www.baomi.org.cn/portal/main-api/v2/activity/exam/saveExamResultJc.do"
        payload = json.dumps({
            "examId": '8ad5a4cf95a7e09701961d54fa6f00d8',
            "examResult": json.dumps(examResult),
            "startDate": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "randomId": questions['data']['randomId']
        })
        response = self.session.post(url, data=payload)
        self.log.info(response.text)

    def finish_exam(self):
        url = f"https://www.baomi.org.cn/portal/main-api/v2/studyTime/updateCoursePackageExamInfo.do?courseId={self.courseId}&orgId=&isExam=1&isCertificate=0&examResult=100"
        try:
            response = self.session.get(url)
            response.raise_for_status()  # 检查响应状态码
            message = response.json()['message']
            self.log.info(message)
        except requests.exceptions.RequestException as e:
            self.log.error(f"完成考试失败: {e}")

    def get_course_user_statistic(self):
        url = f"https://www.baomi.org.cn/portal/main-api/v2/coursePacket/getCourseUserStatistic?coursePacketId={self.courseId}&token={self.token}"
        response = self.session.get(url).json()
        gradeSum = response['data']['gradeSum']
        totalGrade = response['data']['totalGrade']
        return gradeSum == totalGrade

    def run(self):
        self.login()
        directory_ids = self.get_directory_ids()
        for directory in directory_ids:
            self.log.debug(directory)
            sub_directories = directory['subDirectory']
            for sub_dir in sub_directories:
                self.process_video(sub_dir['SYS_UUID'])
        #
        self.save_exam_result()
        self.finish_exam()
        time.sleep(10)


#
if __name__ == '__main__':
    BaoMiGuan("账号", "密码", "21c7d935-dd53-49d2-a95f-dc0f3e14ced7").run()
