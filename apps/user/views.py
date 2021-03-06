import json
import time
from datetime import datetime

from captcha.helpers import captcha_image_url
from captcha.models import CaptchaStore
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail
from django.db.models import Q
from django.http import Http404, HttpResponse,JsonResponse
from django.shortcuts import render, redirect,reverse

# Create your views here.

from django.contrib.auth.views import method_decorator,login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.views.generic.base import View
from django_filters.rest_framework import DjangoFilterBackend
from pytz import unicode
from rest_framework import filters
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_jwt.authentication import JSONWebTokenAuthentication

from apps.article.models import Article, Category_Article
from apps.article.serializers import ArticleSerializer
from apps.article.views import StandardResultsSetPagination
from apps.uitls.EmailToken import token_confirm
from apps.uitls.email_send import send_register_email
from apps.uitls.permissions import IsOwnerOrReadOnly
from apps.user.filter import CategoryFilter, UserFilter
from apps.user.models import User, Follows, VerifyCode
from apps.user.serializers import UserSerializer
from website import settings
from .forms import CaptchaTestForm, LoginForms, Follow_Forms, RegisterForm, ModifyForm, EmailForm, InfoForm
from rest_framework import viewsets, mixins, status, permissions
from rest_framework.pagination import PageNumberPagination

def test(request):
    form = CaptchaTestForm()
    return render(request,'test.html',{'form':form})

def captcha_refresh(request):
    print('=========')
    """  Return json with new captcha for ajax refresh request """
    if not request.is_ajax():
 # 只接受ajax提交
        raise Http404
    new_key = CaptchaStore.generate_key()
    to_json_response = {
        'key': new_key,
        'image_url': captcha_image_url(new_key),
    }
    print(to_json_response)
    return HttpResponse(json.dumps(to_json_response), content_type='application/json')

def yan(request):
    cs = CaptchaStore.objects.filter(response=request.POST['response'], hashkey=request.POST['hashkey'])
    print(cs)
    if cs:
        return JsonResponse({"valid":True})
    else:
        return JsonResponse({'valid':False})




    #===============

class CustomBackend(ModelBackend):
    """进行手机登录验证"""

    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            user = User.objects.get(Q(email=username) | Q(username=username))
            if user.check_password(password):
                return user
        except Exception as e:
            return None


def login_view(request):
    if request.method == 'GET':
        return render(request,'pc/logoin.html')
    if request.method == 'POST':
        form = LoginForms(request.POST)
        if form.is_valid():
            telephone = form.cleaned_data.get('telephone')
            password = form.cleaned_data.get('password')
            remember = form.cleaned_data.get('remember')
            user = authenticate(request,username=telephone,password=password)
            if user:
                if user.is_active:
                    login(request,user)
                    if remember:
                        request.session.set_expiry(None)
                    else:
                        request.session.set_expiry(0)
                    return JsonResponse({"code":200,"message":"","data":{}})
                    #return restful.result()
                else:
                    return JsonResponse({"code": 401, "message": "此账号暂未激活，请联系管理员", "data": {}})
                    #return restful.unauth(message='此账号暂无权限，请联系管理员')
            else:
                return JsonResponse({"code": 400, "message": "账号或者密码错误", "data": {}})
                #return restful.params_error(message="手机号码或者密码错误")
        else:
            errors = form.get_errors()
            return JsonResponse({"code":400,"message":"","data":errors})
            #return restful.params_error(message=errors)

def logout_view(request):
    logout(request)
    return redirect('/index')


class Register(View):
    """
    注册
    """
    def get(self,request):
        return render(request,'pc/register.html')
    def post(self, request):
        form = RegisterForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username','')
            email = form.cleaned_data.get('email', '')
            password = form.cleaned_data.get('password', '')
            users = User()
            users.username = username
            users.password =make_password(password)
            users.email = email
            users.is_active = False
            users.save()
            token = token_confirm.generate_validate_token(username)
            # message = "\n".join([u'{0},欢迎加入我的博客'.format(username), u'请访问该链接，完成用户验证,该链接1个小时内有效',
            #                      '/'.join([settings.DOMAIN, 'activate', token])])
            # send_mail(u'注册用户验证信息', message, settings.EMAIL_HOST_USER, [email], fail_silently=False)
            send_register_email(email=email,username=username,token=token,send_type="register")
            return JsonResponse({'valid':True,'status':200, 'message': u"请登录到注册邮箱中验证用户，有效期为1个小时"})
        return JsonResponse({'status':400,'data':form.errors,'valid':False})


def active_user(request, token):
    #激活验证
    try:
        username = token_confirm.confirm_validate_token(token)
    except:
        username = token_confirm.remove_validate_token(token)
        users = User.objects.filter(username=username)
        for user in users:
            if user.is_active==False:
                user.delete()
                return render(request, 'pc/message.html', {'message': u'对不起，验证链接已经过期，请重新<a href=\"' + unicode(settings.DOMAIN) + u'/signup\">注册</a>'})
            else:
                return render(request, 'pc/message.html', {'message': u'此账号已经验证过，请重新<a href=\"' + unicode(settings.DOMAIN) + u'/signup\">注册</a>'})
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return render(request, 'pc/message.html', {'message': u"对不起，您所验证的用户不存在，请重新注册"})
    user.is_active = True
    user.save()
    message = u'验证成功，请进行<a href=\"' + unicode(settings.DOMAIN) + u'/login\">登录</a>操作'
    return render(request, 'pc/message.html', {'message':message})


@method_decorator(login_required(login_url='/login'),name='dispatch')
class ResetUserView(View):
    """更换邮箱发送验证码"""
    def post(self,request):
        email = request.POST.get('email')
        username = request.POST.get('username')
        if email and username is not None:
            if User.objects.filter(email=email):
                return JsonResponse({'status':400,'message':'邮箱已经存在'})
            send_register_email(email=email, username=username,send_type='update_email')
            return JsonResponse({'status': 200, 'message': u"验证码发送成功，有效期为30分钟"})
        return JsonResponse({'status':400,'message':'用户名与邮箱不能为空'})


@method_decorator(login_required(login_url='/login'),name='dispatch')
class EmailView(View):
    """更换邮箱"""
    def post(self,request):
        forms = EmailForm(request.POST)
        if forms.is_valid():

            email = forms.cleaned_data.get('email')
            username = forms.cleaned_data.get('username')
            code = forms.cleaned_data.get('code')
            end_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() - 1800))
            items = VerifyCode.objects.filter(send_time__lt=end_time)
            for item in items:
                item.delete()
            exitsed = VerifyCode.objects.filter(code__icontains=code,email=email,send_type='update_email')

            if exitsed:
                user=request.user
                user.email=email
                user.save()
                return JsonResponse({'status': 200, 'message': '修改成功,请重新登录'})
            else:
                return JsonResponse({'status': 400, 'message': '验证码已过期或错误'})
        return JsonResponse({'status':400,'message':'验证失败请检查后提交'})


@method_decorator(login_required(login_url='/login'),name='dispatch')
class Modify(View):
    """密码修改"""
    def post(self,request):
         forms = ModifyForm(request.POST)
         if forms.is_valid():
             pwd1 = forms.cleaned_data.get('password')
             pwd2 = forms.cleaned_data.get('password1')
             email = forms.cleaned_data.get('email')
             if pwd1!=pwd2:
                 return JsonResponse({'status':400,"email":email,"message":"密码不一致"})
             User.objects.filter(email=email).update(password=make_password(pwd2))
             return JsonResponse({'status':200,"email":email,"message":"密码修改成功"})
         else:
            email = request.POST.get('email')
            return JsonResponse({'status':400,"email":email, "message":'验证失败请检查后提交'})


class Author(View):
    @method_decorator(login_required(login_url='/login'))
    def post(self,request):
        froms = Follow_Forms(request.POST)
        username = request.POST.get('username')
        if froms.is_valid():
            follow = Follows()
            if request.POST.get('follow') == str(username):
                return JsonResponse({'status': 201, 'message': '不能自己关注自己'})
            else:
                cun = Follows.objects.filter(follow=froms.cleaned_data.get('follow'),fan=username)
                if cun:
                    cun.delete()
                    return JsonResponse({'status': 200, 'message': '已取消关注'})
                follow.follow = froms.cleaned_data.get('follow')
                follow.fan_id = request.user.id
                follow.save()
                return JsonResponse({'status':200,'message':'成功关注'})
        else:
            return JsonResponse({'status':400,'message':'失败'})



"""个人中心"""
@method_decorator(login_required(login_url='/login'),name='dispatch')
class Person(View):

    @method_decorator(login_required(login_url='/login'),name='dispatch')
    def get(self,request):

        category = Category_Article.objects.all()
        count = User.objects.filter(follow__fan__id=request.user.id)
        floow = User.objects.filter(fan__follow_id=request.user.id)

        return render(request,'pc/person/index.html',{'category':category,'count':count,'floow':floow})


class PersonDetaile(View):
    """个人中心（他人）"""
    def get(self,request,article_id):
        category = Category_Article.objects.all()
        count = User.objects.filter(follow__fan__id=article_id)
        floow = User.objects.filter(fan__follow_id=article_id)
        user = User.objects.get(id=article_id)

        is_active = Follows.objects.filter(follow=article_id, fan=request.user.id).exists()
        if article_id ==request.user.id:
            return redirect(reverse('user:person'))

        return render(request, 'pc/person/indexOthers.html', {'category':category, 'count':count, 'floow':floow, 'user':user,'is_active':is_active})

@login_required(login_url='/login')
def Profile(request):
    """
    人脉
    :param request:
    :return:
    """
    count = User.objects.filter(follow__fan__id=request.user.id)
    floow = User.objects.filter(fan__follow_id=request.user.id)
    user = User.objects.get(id=request.user.id)

    return render(request, 'pc/person/profile.html',{'count':count,'floow':floow,'user':user})


def ProfileOthers(request,article_id):
    """
    人脉
    :param request:
    :return:
    """
    category = Category_Article.objects.all()
    count = User.objects.filter(follow__fan__id=article_id)
    floow = User.objects.filter(fan__follow_id=article_id)
    user = User.objects.get(id=article_id)
    is_active = Follows.objects.filter(follow=article_id, fan=request.user.id).exists()
    return render(request, 'pc/person/profileOthers.html',{'category':category, 'count':count, 'floow':floow, 'user':user,'is_active':is_active})



@csrf_exempt
def Guan(request):
    """取关"""
    if request.method == 'POST':
        if request.user.id is not None:
            froms = Follow_Forms(request.POST)
            if froms.is_valid():
                floows = froms.cleaned_data.get('follow','')
                user = request.POST.get('user','')
                table=Follows.objects.filter(follow_id=floows,fan_id=user).delete()
                return JsonResponse({'message':'ok','data':200})
        else:
            return JsonResponse({'massage':'未登录'})
    return HttpResponse()


@login_required(login_url='/login')
def Info(request):
    """
    资料
    :param request:
    :return:
    """
    count = User.objects.filter(follow__fan__id=request.user.id)
    floow = User.objects.filter(fan__follow_id=request.user.id)
    user = User.objects.get(id=request.user.id)

    if request.method == 'POST':

        print( request.POST.get('username'))
        forms = InfoForm(request.POST)
        if forms.is_valid():
            username = forms.cleaned_data.get('username')
            info = request.POST.get('info')
            position = request.POST.get('position')
            file = request.FILES.get('file')
            user = request.user
            user.username=username
            user.info=info
            user.position=position
            if file:
                user.user_imag=file
            user.save()
            return JsonResponse({'status':200,'message':'修改成功'})
        return JsonResponse({'status':400,'message':'提交失败'})
    return render(request,'pc/person/info.html',{'count':count,'floow':floow,'user':user})


class InfoOthers(View):
    def get(self,request,article_id):
        category = Category_Article.objects.all()
        count = User.objects.filter(follow__fan__id=article_id)
        floow = User.objects.filter(fan__follow_id=article_id)
        user = User.objects.get(id=article_id)
        is_active = Follows.objects.filter(follow=article_id, fan=request.user.id).exists()
        return render(request,'pc/person/infoOthers.html',{'category':category, 'count':count, 'floow':floow, 'user':user,'is_active':is_active})

"""drf"""
class PersonApiabstohr(viewsets.ReadOnlyModelViewSet):
    queryset = Article.objects.filter(is_show=True)
    serializer_class = ArticleSerializer
    filter_backends = (DjangoFilterBackend,)
    filter_class = CategoryFilter
    authentication_classes = [SessionAuthentication, JSONWebTokenAuthentication]
    pagination_class = StandardResultsSetPagination


class PersonApi(PersonApiabstohr):
    """
    个人中心
    """
    permission_classes = (IsAuthenticated, IsOwnerOrReadOnly)  # 未登录禁止访问
    # def list(self, request, *args, **kwargs):
    #         queryset =  Article_add.objects.filter(authors_id=self.request.user.id).order_by('-add_time')
    #         serializer = ArticleSerializer(queryset, many=True)
    #
    #         page = self.paginate_queryset(queryset)
    #         if page is not None:
    #             serializer = self.get_serializer(page, many=True)
    #             return self.get_paginated_response(serializer.data)
    #         return Response(serializer.data)
    # def get_queryset(self):
    #     return Article_add.objects.filter(authors_id=self.request.user.id)

    def get_queryset(self):
        """
        This view should return a list of all the purchases
        for the currently authenticated user.
        """
        user = self.request.user
        #User.objects.filter()

        # user_id = self.request.query_params.get('pk')
        # if user_id:
        #     return Article_add.objects.filter(authors_id=user_id).filter(is_show=True).order_by('-add_time')
        # else:
        return Article.objects.filter(authors_id=self.request.user.id).filter(is_show=True).order_by(
                '-add_time')


class PersonOthers(PersonApiabstohr):
    """
    他个人中心
    """
    def get_queryset(self):
        """
        This view should return a list of all the purchases
        for the currently authenticated user.
        """
        user_id = self.request.query_params.get('pk')
        if user_id:
            return Article.objects.filter(authors_id=user_id).filter(is_show=True).order_by('-add_time')


class UserGetAllInfo(mixins.ListModelMixin,mixins.UpdateModelMixin,viewsets.GenericViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = (IsAuthenticated, IsOwnerOrReadOnly)  # 未登录禁止访问
    authentication_classes = [SessionAuthentication, JSONWebTokenAuthentication]


class UserGetInfo(UserGetAllInfo):
    def get_queryset(self):
        return User.objects.filter(pk=self.request.user.id)


class UserDisbale(mixins.ListModelMixin,mixins.UpdateModelMixin,viewsets.GenericViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = (IsAuthenticated, IsOwnerOrReadOnly)  # 未登录禁止访问
    authentication_classes = [SessionAuthentication, JSONWebTokenAuthentication]

    pass